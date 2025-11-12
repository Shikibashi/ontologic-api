# app/config/settings.py
from __future__ import annotations
import warnings
from pathlib import Path
import tomllib
from typing import Any, Dict, Tuple
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

# Suppress pydantic-settings warning about missing /run/secrets directory
warnings.filterwarnings("ignore", message='directory "/run/secrets" does not exist', category=UserWarning)

class TOMLSettingsSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls, base_dir: Path, env: str):
        super().__init__(settings_cls)
        self.base_dir = base_dir
        self.env = env

    def get_field_value(self, field_info, field_name: str):
        # Not used for our implementation
        return None

    def _flatten_dict(self, data: Dict[str, Any], parent_key: str = "") -> Dict[str, Any]:
        """
        Flatten nested dictionary from TOML structure to match Settings field names.

        Handles special naming conventions:
        - models.llm -> llm_model
        - features.document_uploads -> document_uploads_enabled
        - qdrant.url -> qdrant_url
        - For other nested keys, uses the leaf name

        Args:
            data: Nested dictionary from TOML file
            parent_key: Parent key for recursion (used to build full path)

        Returns:
            Flattened dictionary with Settings-compatible field names
        """
        items = []
        for key, value in data.items():
            new_key = f"{parent_key}.{key}" if parent_key else key

            if isinstance(value, dict) and not self._is_special_dict(key, value):
                # Recursively flatten nested dicts (except special cases like oauth.providers)
                items.extend(self._flatten_dict(value, new_key).items())
            else:
                items.append((new_key, value))

        # Apply naming mappings to match Settings field names
        result: Dict[str, Any] = {}
        for key, value in items:
            mapped_key = self._map_toml_key_to_settings_field(key)

            # Handle potential collisions by preferring more specific keys
            if mapped_key in result:
                if key.count(".") > 0:
                    result[mapped_key] = value
            else:
                result[mapped_key] = value

        return result

    def _is_special_dict(self, key: str, value: Dict[str, Any]) -> bool:
        """
        Check if a dictionary should be kept as-is rather than flattened.

        Some nested structures like oauth.providers should remain as dictionaries.
        """
        # Keep oauth providers as nested structure, but allow oauth.enabled to be flattened
        if key == "providers" or (key == "oauth" and "providers" in value):
            return True
        # Keep subscription_tiers and rate_limits as flattened structures
        if key in ["subscription_tiers", "rate_limits"]:
            return False
        return False

    def _map_toml_key_to_settings_field(self, toml_key: str) -> str:
        """
        Map TOML key paths to Settings field names.

        Handles special naming conventions and returns the appropriate field name.
        """
        # Special mappings for fields that don't follow the leaf-name pattern
        special_mappings = {
            "models.llm": "llm_model",
            "features.document_uploads": "document_uploads_enabled",
            "qdrant.url": "qdrant_url",
            "qdrant.local.url": "local_qdrant_url",
            "context_window.default": "default_context_window",
            "context_window.max_context": "max_context_window",
            "llm.request_timeout_seconds": "llm_request_timeout",
            "llm.generation_timeout_seconds": "llm_generation_timeout",
            "llm.chat_timeout_seconds": "llm_chat_timeout",
            "llm.vet_timeout_seconds": "llm_vet_timeout",
            "logging.log_dir": "log_dir",
            "compression.enabled": "compression_enabled",
            "compression.minimum_size": "compression_minimum_size",
            "payments.enabled": "payments_enabled",
            "payments.grace_period_days": "subscription_grace_period_days",
            "oauth.enabled": "oauth_enabled",
            "subscription_tiers.free.requests_per_month": "free_tier_requests_per_month",
            "subscription_tiers.basic.requests_per_month": "basic_tier_requests_per_month",
            "subscription_tiers.premium.requests_per_month": "premium_tier_requests_per_month",
            "subscription_tiers.academic.requests_per_month": "academic_tier_requests_per_month",
        }

        # Check for exact match in special mappings
        if toml_key in special_mappings:
            return special_mappings[toml_key]

        # For nested keys not in special mappings, use the leaf name
        if "." in toml_key:
            return toml_key.split(".")[-1]

        # Top-level keys pass through as-is
        return toml_key

    def _read(self, name: str) -> Dict[str, Any]:
        p = self.base_dir / name
        if not p.exists():
            return {}
        with p.open("rb") as f:
            return tomllib.load(f)

    def prepare_field_value(self, field_name: str, field, value, value_from):
        return value

    def __call__(self) -> Dict[str, Any]:
        """
        Load and merge TOML configuration files.

        Loads base.toml first, then overlays {env}.toml, then flattens
        the nested structure to match Settings field names.

        Returns:
            Flattened dictionary ready for Pydantic Settings
        """
        # Load TOML files in order: base.toml -> {env}.toml
        data: Dict[str, Any] = {}
        data.update(self._read("base.toml"))
        data.update(self._read(f"{self.env}.toml"))

        # Flatten nested structure to match Settings field names
        flattened = self._flatten_dict(data)

        # Optional: enable when diagnosing configuration loading issues
        # from app.core.logger import log
        # log.debug(f"TOML configuration loaded from {self.env}.toml: {list(flattened.keys())}")

        return flattened

class Settings(BaseSettings):
    """
    Settings class for Ontologic API configuration.

    Configuration is loaded from multiple sources in priority order:
    1. Constructor arguments (highest priority)
    2. TOML files (base.toml + {env}.toml from app/config/toml/)
    3. Environment variables with APP_ prefix
    4. Docker secrets from /run/secrets

    Note: TOML files use nested sections ([chat], [qdrant], etc.) for organization,
    but these are automatically flattened to match Settings field names. For example:
    - [models] llm = "qwen3:8b" becomes llm_model
    - [chat] chat_use_pdf_context = true becomes chat_use_pdf_context
    - [qdrant] url = "http://..." becomes qdrant_url

    Pydantic applies sources in order, so any APP_* environment variable overrides
    the corresponding value loaded from TOML files.

    Examples:
        Verify settings are loaded correctly:
        >>> settings = get_settings()
        >>> settings.log_configuration_summary()
        >>> is_valid, issues = settings.validate_pdf_context_config()
        >>> if not is_valid:
        ...     print(f"Configuration issues: {issues}")

        Check PDF context configuration:
        >>> pdf_config = settings.get_pdf_context_config()
        >>> print(f"PDF context enabled: {pdf_config['enabled']}")
    """
    # Core application settings  
    env: str = Field("dev")  # Will be prefixed as APP_ENV
    
    # Database configuration
    database_url: str = Field("sqlite:///ontologic.db")  # Will use APP_DATABASE_URL or ONTOLOGIC_DB_URL
    
    # Qdrant configuration  
    qdrant_url: str = Field("http://127.0.0.1:6333")  # Will use APP_QDRANT_URL
    qdrant_api_key: SecretStr | None = Field(None)  # Will use APP_QDRANT_API_KEY
    
    # Local Qdrant configuration (for development/backup)
    local_qdrant_url: str = Field("http://localhost:6333")  # Will use APP_LOCAL_QDRANT_URL
    local_qdrant_api_key: SecretStr | None = Field(None)  # Will use APP_LOCAL_QDRANT_API_KEY
    
    # LLM configuration
    openai_api_key: SecretStr | None = Field(None)  # Will use APP_OPENAI_API_KEY
    
    # Security configuration
    session_secret: SecretStr | None = Field(None)  # Will use APP_SESSION_SECRET
    cors_origins: list[str] = Field(default_factory=list)  # Will use APP_CORS_ORIGINS (comma-separated)

    # Redis configuration
    redis_enabled: bool = Field(True)  # Will use APP_REDIS_ENABLED 
    redis_url: str = Field("redis://localhost:6379")  # Will use APP_REDIS_URL
    
    # Feature flags
    use_llama_index_workflows: bool = Field(False)  # Will use APP_USE_LLAMA_INDEX_WORKFLOWS
    
    # Fusion search configuration
    use_fusion_search: bool = Field(False)  # Will use APP_USE_FUSION_SEARCH
    fusion_methods: str = Field("hyde,rag_fusion")  # Will use APP_FUSION_METHODS
    fusion_rrf_k: int = Field(60)  # Will use APP_FUSION_RRF_K
    fusion_max_queries: int = Field(4)  # Will use APP_FUSION_MAX_QUERIES
    enable_compilation: bool = Field(True)  # Will use APP_ENABLE_COMPILATION
    chat_history: bool = Field(True)  # Will use APP_CHAT_HISTORY
    
    # Workflow configuration
    max_retries: int = 3
    timeout: int = 300
    batch_size: int = 10
    
    # LLM model configuration (loaded from TOML files)
    llm_model: str = Field("qwen3:8b")  # From models.llm in TOML
    embed_model: str = Field("avr/sfr-embedding-mistral")  # From models.embed_model in TOML
    splade_model: str = Field("naver/splade-cocondenser-ensembledistil")  # From models.splade_model in TOML
    
    # LLM timeout configuration
    llm_request_timeout: int = Field(300)  # 5 minutes default
    llm_generation_timeout: int = Field(300)
    llm_chat_timeout: int = Field(300)
    llm_vet_timeout: int = Field(300)
    
    # Context window configuration
    default_context_window: int = Field(8192)
    max_context_window: int = Field(32000)
    
    # OAuth configuration (placeholder for future)
    oauth_enabled: bool = Field(False)
    oauth_providers: str = Field("")  # Comma-separated list
    
    # Document uploads configuration
    document_uploads_enabled: bool = Field(
        True,
        description="Enable document upload/delete endpoints. "
                    "SECURITY: Set to False in production until authentication is implemented. "
                    "Without authentication, anyone can upload/delete documents using any username."
    )
    max_upload_size_mb: int = Field(50)  # Will use APP_MAX_UPLOAD_SIZE_MB

    # Logging configuration
    log_dir: str = Field(
        "logs",
        description="Directory path for application log files. "
                    "Can be absolute or relative to the application root. "
                    "Directory will be created automatically if it doesn't exist."
    )

    # Response compression configuration
    compression_enabled: bool = Field(
        True,
        description="Enable GZip compression for HTTP responses. "
                    "Reduces bandwidth usage for large JSON responses. "
                    "Recommended for production deployments."
    )
    compression_minimum_size: int = Field(
        1000,
        ge=100,
        le=10000,
        description="Minimum response size in bytes to trigger compression. "
                    "Responses smaller than this threshold are not compressed. "
                    "Default: 1000 bytes (1KB). Range: 100-10000 bytes."
    )

    # Cache warming configuration
    cache_warming_enabled: bool = Field(
        True,
        description="Enable cache warming during application startup. "
                    "Pre-loads frequently accessed data into Redis cache to improve "
                    "cold-start performance. Includes philosopher collections and common embeddings."
    )
    cache_warming_items: str = Field(
        "collections,embeddings",
        description="Comma-separated list of items to warm. "
                    "Options: collections (philosopher collection names), "
                    "embeddings (common philosopher name embeddings). "
                    "Example: 'collections,embeddings' or 'collections' only."
    )

    chat_use_pdf_context: bool = Field(
        False,
        description="Enable PDF context integration in chat. "
                    "When enabled, user documents are searched and merged with philosopher context. "
                    "Requires document_uploads_enabled=True and user documents to be uploaded."
    )
    pdf_context_limit: int = Field(
        5,
        ge=1,
        le=20,
        description="Maximum number of PDF chunks to include in chat context. "
                    "Higher values provide more context but may exceed token limits."
    )

    # JWT Authentication configuration
    jwt_secret: SecretStr = Field(
        default=SecretStr("CHANGE_THIS_IN_PRODUCTION"),
        description="Secret key for JWT token signing. MUST be changed in production. "
                    "Generate with: openssl rand -hex 32"
    )
    jwt_lifetime_seconds: int = Field(
        3600,
        description="JWT token lifetime in seconds (default: 1 hour)"
    )
    jwt_algorithm: str = Field(
        "HS256",
        description="JWT signing algorithm"
    )

    # Payment and Stripe configuration
    stripe_publishable_key: SecretStr | None = Field(
        None,
        description="Stripe publishable key for client-side integration. "
                    "Set via APP_STRIPE_PUBLISHABLE_KEY environment variable."
    )
    stripe_secret_key: SecretStr | None = Field(
        None,
        description="Stripe secret key for server-side API calls. "
                    "Set via APP_STRIPE_SECRET_KEY environment variable."
    )
    stripe_webhook_secret: SecretStr | None = Field(
        None,
        description="Stripe webhook endpoint secret for signature validation. "
                    "Set via APP_STRIPE_WEBHOOK_SECRET environment variable."
    )

    # Stripe Price IDs (configured in Stripe Dashboard)
    stripe_price_basic_monthly: str = Field(
        "",
        description="Stripe Price ID for Basic monthly subscription. "
                    "Set via APP_STRIPE_PRICE_BASIC_MONTHLY environment variable."
    )
    stripe_price_premium_monthly: str = Field(
        "",
        description="Stripe Price ID for Premium monthly subscription. "
                    "Set via APP_STRIPE_PRICE_PREMIUM_MONTHLY environment variable."
    )
    stripe_price_academic_monthly: str = Field(
        "",
        description="Stripe Price ID for Academic monthly subscription. "
                    "Set via APP_STRIPE_PRICE_ACADEMIC_MONTHLY environment variable."
    )

    # Payment feature flags
    payments_enabled: bool = Field(
        False,
        description="Enable payment processing and subscription features. "
                    "When disabled, all users have free tier access. "
                    "Set via APP_PAYMENTS_ENABLED environment variable."
    )
    subscription_grace_period_days: int = Field(
        3,
        ge=0,
        le=30,
        description="Grace period in days before restricting access after payment failure. "
                    "Set via APP_SUBSCRIPTION_GRACE_PERIOD_DAYS environment variable."
    )
    subscription_fail_open: bool = Field(
        False,
        description="Enable fail-open mode for subscription checks. When False (default), "
                    "subscription check failures raise HTTP 503 errors (fail-closed). "
                    "When True, subscription check failures are logged but allow requests "
                    "to proceed (fail-open/graceful degradation). Fail-closed is recommended "
                    "for production to prevent unauthorized access during system issues. "
                    "Set via APP_SUBSCRIPTION_FAIL_OPEN environment variable."
    )

    # Subscription tier limits (can be overridden in TOML)
    free_tier_requests_per_month: int = Field(
        1000,
        ge=0,
        description="API requests per month for free tier users"
    )
    basic_tier_requests_per_month: int = Field(
        10000,
        ge=0,
        description="API requests per month for basic tier subscribers"
    )
    premium_tier_requests_per_month: int = Field(
        100000,
        ge=0,
        description="API requests per month for premium tier subscribers"
    )
    academic_tier_requests_per_month: int = Field(
        50000,
        ge=0,
        description="API requests per month for academic tier subscribers"
    )

    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        """Parse comma-separated CORS origins from environment variable."""
        if isinstance(v, str):
            # Split by comma and strip whitespace
            return [origin.strip() for origin in v.split(',') if origin.strip()]
        return v if v is not None else []

    model_config = dict(
        env_prefix="APP_", 
        secrets_dir="/run/secrets",
        extra='allow'  # Allow extra fields from TOML for backward compatibility
    )

    @classmethod
    def settings_customise_sources(  # NOTE: British spelling is correct
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # prefer explicit constructor, then ENV var, else "dev"
        env = "dev"  # Default
        
        # Try to get from init settings first
        if hasattr(init_settings, 'init_kwargs') and init_settings.init_kwargs:
            env = init_settings.init_kwargs.get("env", env)
        
        # Fall back to environment variable
        import os
        env = os.environ.get("ENV", env)
        
        toml_dir = Path(__file__).parent / "toml"
        toml_source = TOMLSettingsSource(settings_cls, base_dir=toml_dir, env=env)
        return (
            init_settings,        # kwargs on Settings(...) - highest priority
            env_settings,         # env vars override TOML
            toml_source,          # base + env TOML
            file_secret_settings, # /run/secrets, k8s, etc. - lowest priority
        )

    def log_configuration_summary(self) -> None:
        """Log a summary of critical configuration settings for debugging and verification."""
        from app.core.logger import log

        log.info("Configuration Summary:")
        log.info(f"  Environment: {self.env}")
        log.info(f"  Database: {self.database_url}")
        log.info(f"  Qdrant URL: {self.qdrant_url}")
        log.info(f"  Redis enabled: {self.redis_enabled}")
        log.info(f"  Log directory: {self.log_dir}")
        log.info(f"  Chat history: {self.chat_history}")
        log.info(f"  PDF context enabled: {self.chat_use_pdf_context}")
        log.info(f"  PDF context limit: {self.pdf_context_limit}")
        log.info(f"  Document uploads enabled: {self.document_uploads_enabled}")
        log.info(f"  Max upload size: {self.max_upload_size_mb}MB")
        log.info(f"  JWT lifetime: {self.jwt_lifetime_seconds}s")
        log.info(f"  LLM model: {self.llm_model}")
        log.info(f"  Embed model: {self.embed_model}")
        log.info(f"  Compression enabled: {self.compression_enabled}")
        log.info(f"  Cache warming enabled: {self.cache_warming_enabled}")
        log.info(f"  Payments enabled: {self.payments_enabled}")
        if self.payments_enabled:
            log.info(f"  Subscription grace period: {self.subscription_grace_period_days} days")
            log.info(f"  Free tier limit: {self.free_tier_requests_per_month} requests/month")
            log.info(f"  Basic tier limit: {self.basic_tier_requests_per_month} requests/month")
            log.info(f"  Premium tier limit: {self.premium_tier_requests_per_month} requests/month")
            log.info(f"  Academic tier limit: {self.academic_tier_requests_per_month} requests/month")
        if self.cache_warming_enabled:
            log.info(f"  Cache warming items: {self.cache_warming_items}")
        if self.compression_enabled:
            log.info(f"  Compression minimum size: {self.compression_minimum_size} bytes")

    def get_pdf_context_config(self) -> dict:
        """Get PDF context configuration as a dictionary for easy inspection."""
        return {
            "enabled": self.chat_use_pdf_context,
            "limit": self.pdf_context_limit,
            "document_uploads_enabled": self.document_uploads_enabled,
            "max_upload_size_mb": self.max_upload_size_mb,
            "requires_authentication": True,
            "qdrant_url": self.qdrant_url,
        }

    def validate_pdf_context_config(self) -> tuple[bool, list[str]]:
        """Validate PDF context configuration and return any issues."""
        issues: list[str] = []

        if self.chat_use_pdf_context and not self.document_uploads_enabled:
            issues.append("PDF context is enabled but document uploads are disabled")

        if self.pdf_context_limit < 1 or self.pdf_context_limit > 20:
            issues.append(
                f"PDF context limit ({self.pdf_context_limit}) is outside valid range (1-20)"
            )

        if self.chat_use_pdf_context and not self.qdrant_url:
            issues.append("PDF context requires Qdrant URL to be configured")

        return len(issues) == 0, issues

    def validate_production_secrets(self) -> tuple[bool, list[str]]:
        """Validate that production secrets are properly configured.

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues: list[str] = []

        if self.env.lower() in ("prod", "production"):
            # Check JWT secret
            jwt_secret = self.jwt_secret.get_secret_value()
            if jwt_secret == "CHANGE_THIS_IN_PRODUCTION":
                issues.append("JWT secret is using default value - set APP_JWT_SECRET")
            elif len(jwt_secret) < 32:
                issues.append(f"JWT secret is too short ({len(jwt_secret)} chars, minimum 32)")

            # Check session secret if set
            if self.session_secret:
                session_secret = self.session_secret.get_secret_value()
                if len(session_secret) < 32:
                    issues.append(f"Session secret is too short ({len(session_secret)} chars, minimum 32)")

            # Check Stripe secrets if payments enabled
            if self.payments_enabled:
                # Check stripe_secret_key - extract value, strip whitespace, check for emptiness
                if not self.stripe_secret_key or not self.stripe_secret_key.get_secret_value().strip():
                    issues.append("Payments enabled but APP_STRIPE_SECRET_KEY not set")

                # Check stripe_webhook_secret - extract value, strip whitespace, check for emptiness
                if not self.stripe_webhook_secret or not self.stripe_webhook_secret.get_secret_value().strip():
                    issues.append("Payments enabled but APP_STRIPE_WEBHOOK_SECRET not set")

                # Check stripe_publishable_key - ensure it is present and non-empty
                if not self.stripe_publishable_key or not self.stripe_publishable_key.get_secret_value().strip():
                    issues.append("Payments enabled but APP_STRIPE_PUBLISHABLE_KEY not set")

                # Check Stripe price IDs - ensure configured when payments enabled
                if not self.stripe_price_basic_monthly.strip():
                    issues.append("Payments enabled but APP_STRIPE_PRICE_BASIC_MONTHLY not set")
                if not self.stripe_price_premium_monthly.strip():
                    issues.append("Payments enabled but APP_STRIPE_PRICE_PREMIUM_MONTHLY not set")
                if not self.stripe_price_academic_monthly.strip():
                    issues.append("Payments enabled but APP_STRIPE_PRICE_ACADEMIC_MONTHLY not set")

        return len(issues) == 0, issues

# Cached settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
