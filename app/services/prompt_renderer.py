from pathlib import Path
from typing import Any, Dict
from jinja2 import Environment, FileSystemLoader, select_autoescape
from functools import lru_cache
import json
import hashlib


class PromptRenderer:
    def __init__(self, templates_dir: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent  # app/
        self.templates_dir = templates_dir or (base_dir / "prompts")
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(enabled_extensions=(".j2",)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @classmethod
    async def start(cls, templates_dir: Path | None = None) -> 'PromptRenderer':
        """
        Async factory method for lifespan-managed initialization.

        Args:
            templates_dir: Optional custom templates directory path

        Returns:
            Initialized PromptRenderer instance
        """
        from app.core.logger import log
        instance = cls(templates_dir=templates_dir)
        log.info("PromptRenderer initialized for lifespan management")
        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        from app.core.logger import log
        # PromptRenderer is stateless and has no resources to clean up
        # This method exists for consistency with other lifespan-managed services
        log.info("PromptRenderer cleaned up")

    @staticmethod
    def _hash_context(context: Dict[str, Any] | None) -> str:
        try:
            payload = json.dumps(context or {}, sort_keys=True, default=str)
        except (TypeError, ValueError, OverflowError) as e:
            # JSON serialization failed - fall back to string representation
            from app.core.logger import log
            log.debug(f"Context serialization failed, using str() fallback: {e}")
            payload = str(context)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @lru_cache(maxsize=256)
    def _render_cached(self, template_path: str, context_hash: str) -> str:
        tmpl = self.env.get_template(template_path)
        # Context will be provided at call-time via render (not used here)
        # We rely on separate cache key including context hash
        return tmpl

    def render(self, template_path: str, context: Dict[str, Any] | None = None) -> str:
        ctx = context or {}
        ctx_hash = self._hash_context(ctx)
        # Fetch compiled template via cache key
        tmpl = self.env.get_template(template_path)
        return tmpl.render(**ctx)
