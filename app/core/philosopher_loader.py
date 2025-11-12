"""
Dynamic philosopher data loader using Jinja2 templates.

This module replaces the hardcoded PHILOSOPHER_INFO dictionary with a 
template-based system that loads philosopher data from structured 
Jinja2 template files.
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import functools
from app.services.prompt_renderer import PromptRenderer
from app.core.logger import log


class PhilosopherLoader:
    """Loads philosopher data dynamically from Jinja2 templates."""
    
    def __init__(self):
        self.prompt_renderer = PromptRenderer()
        self._cache: Dict[str, Any] = {}
        
        # Available philosophers (based on directory structure)
        self.available_philosophers = [
            "Friedrich Nietzsche",
            "John Locke", 
            "Aristotle",
            "Immanuel Kant",
            "David Hume"
        ]
        
        # Map display names to directory names
        self.philosopher_dirs = {
            "Friedrich Nietzsche": "nietzsche",
            "John Locke": "locke",
            "Aristotle": "aristotle", 
            "Immanuel Kant": "kant",
            "David Hume": "hume"
        }
    
    def _load_template_as_list(self, template_path: str) -> List[str]:
        """Load a template and split into list by lines."""
        try:
            content = self.prompt_renderer.render(template_path)
            return [line.strip() for line in content.strip().split('\n') if line.strip()]
        except Exception as e:
            log.warning(f"Failed to load template {template_path}: {e}")
            return []
    
    def _load_priming_passages(self, philosopher_dir: str) -> Dict[str, str]:
        """Load priming passages for a philosopher."""
        # These are the existing template files we already created
        priming_templates = {
            "nietzsche": {
                "madman": f"philosophers/{philosopher_dir}/madman.j2",
                "antichrist": f"philosophers/{philosopher_dir}/antichrist.j2", 
                "zarathustra_creator": f"philosophers/{philosopher_dir}/zarathustra_creator.j2",
                "twilight_idols": f"philosophers/{philosopher_dir}/twilight_idols.j2",
                "beyond_good_evil": f"philosophers/{philosopher_dir}/beyond_good_evil.j2",
            },
            "locke": {
                "essay": f"philosophers/{philosopher_dir}/essay.j2",
                "second_treatise": f"philosophers/{philosopher_dir}/second_treatise.j2",
                "letter_toleration": f"philosophers/{philosopher_dir}/letter_toleration.j2", 
                "essay_identity": f"philosophers/{philosopher_dir}/essay_identity.j2",
            },
            "aristotle": {
                "metaphysics": f"philosophers/{philosopher_dir}/metaphysics.j2",
                "ethics": f"philosophers/{philosopher_dir}/ethics.j2",
                "politics": f"philosophers/{philosopher_dir}/politics.j2",
                "poetics": f"philosophers/{philosopher_dir}/poetics.j2",
            },
            "kant": {
                "critique_pure_reason": f"philosophers/{philosopher_dir}/critique_pure_reason.j2",
                "groundwork_morals": f"philosophers/{philosopher_dir}/groundwork_morals.j2",
                "critique_practical_reason": f"philosophers/{philosopher_dir}/critique_practical_reason.j2",
                "prolegomena": f"philosophers/{philosopher_dir}/prolegomena.j2",
                "critique_judgment": f"philosophers/{philosopher_dir}/critique_judgment.j2",
            },
            "hume": {
                "treatise_reason": f"philosophers/{philosopher_dir}/treatise_reason.j2",
                "treatise_identity": f"philosophers/{philosopher_dir}/treatise_identity.j2",
                "enquiry_understanding": f"philosophers/{philosopher_dir}/enquiry_understanding.j2",
                "enquiry_morals": f"philosophers/{philosopher_dir}/enquiry_morals.j2",
                "dialogues_natural_religion": f"philosophers/{philosopher_dir}/dialogues_natural_religion.j2",
            }
        }
        
        return priming_templates.get(philosopher_dir, {})
    
    def load_philosopher(self, name: str) -> Optional[Dict[str, Any]]:
        """Load complete philosopher data from templates."""
        if name in self._cache:
            return self._cache[name]
            
        if name not in self.philosopher_dirs:
            log.warning(f"Unknown philosopher: {name}")
            return None
            
        philosopher_dir = self.philosopher_dirs[name]
        
        try:
            philosopher_data = {
                "personality": self._load_template_as_list(f"philosophers/{philosopher_dir}/personality.j2"),
                "cognitive_tone": self._load_template_as_list(f"philosophers/{philosopher_dir}/cognitive_tone.j2"),
                "axioms": self._load_template_as_list(f"philosophers/{philosopher_dir}/axioms.j2"),
                "rhetorical_tactics": self._load_template_as_list(f"philosophers/{philosopher_dir}/rhetorical_tactics.j2"),
                "response_protocol": self._load_template_as_list(f"philosophers/{philosopher_dir}/response_protocol.j2"),
                "prompt_priming_passages": self._load_priming_passages(philosopher_dir)
            }
            
            # Cache the result
            self._cache[name] = philosopher_data
            log.info(f"Loaded philosopher data for {name} from templates")
            return philosopher_data
            
        except Exception as e:
            log.error(f"Failed to load philosopher {name}: {e}")
            return None
    
    def get_all_philosophers(self) -> Dict[str, Any]:
        """Load all available philosophers."""
        result = {}
        for name in self.available_philosophers:
            philosopher_data = self.load_philosopher(name)
            if philosopher_data:
                result[name] = philosopher_data
        return result
    
    def get_priming_passage(self, philosopher: str, passage_key: str) -> Optional[str]:
        """Get a specific priming passage for a philosopher."""
        philosopher_data = self.load_philosopher(philosopher)
        if not philosopher_data:
            return None
            
        priming_passages = philosopher_data.get("prompt_priming_passages", {})
        template_path = priming_passages.get(passage_key)
        
        if not template_path:
            return None
            
        try:
            return self.prompt_renderer.render(template_path)
        except Exception as e:
            log.warning(f"Failed to render priming passage {passage_key} for {philosopher}: {e}")
            return None


# Create singleton instance
_philosopher_loader = PhilosopherLoader()

# Create a cached function to get philosopher info
@functools.lru_cache(maxsize=10)
def get_philosopher_info() -> Dict[str, Any]:
    """Get all philosopher information (cached)."""
    return _philosopher_loader.get_all_philosophers()

# Backward compatibility - maintain PHILOSOPHER_INFO interface
PHILOSOPHER_INFO = get_philosopher_info()

def reload_philosopher_info():
    """Reload philosopher information (clears cache)."""
    global PHILOSOPHER_INFO
    _philosopher_loader._cache.clear()
    get_philosopher_info.cache_clear()
    PHILOSOPHER_INFO = get_philosopher_info()