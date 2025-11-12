from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import uvicorn
import argparse
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from app.core.constants import UVICORN_KEEPALIVE_TIMEOUT_SECONDS, UVICORN_GRACEFUL_SHUTDOWN_SECONDS


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern lifespan context manager using async service initialization.
    
    Services are initialized in dependency order and stored in app.state
    for request-time access via dependency injection.
    """
    # Import dependencies inside lifespan to avoid circular imports
    from app.core.logger import log
    from app.core.database import init_db
    from app.services.qdrant_manager import QdrantManager
    from app.services.llm_manager import LLMManager
    from app.core.security import SecurityManager
    from app.services.cache_service import RedisCacheService
    from app.services.auth_service import AuthService
    from app.services.expansion_service import ExpansionService
    from app.services.chat_history_service import ChatHistoryService
    from app.services.chat_qdrant_service import ChatQdrantService
    from app.services.prompt_renderer import PromptRenderer
    from app.services.cache_warming import CacheWarmingService
    from app.workflow_services.paper_workflow import PaperWorkflow
    from app.workflow_services.review_workflow import ReviewWorkflow
    from app.config import get_settings
    from app.config.settings import Settings, TOMLSettingsSource
    
    # ========== STARTUP ==========
    log.info("Starting Ontologic API with modern lifespan management...")
    
    # Get configuration
    settings = get_settings()
    app.state.settings = settings

    log.info("=" * 60)
    log.info("Configuration Loaded Successfully")
    log.info("=" * 60)
    log.info(f"Environment: {settings.env}")
    log.info(f"TOML files loaded: base.toml + {settings.env}.toml")
    log.info("")
    log.info("PDF Context Configuration:")
    log.info(f"  - chat_use_pdf_context: {settings.chat_use_pdf_context}")
    log.info(f"  - pdf_context_limit: {settings.pdf_context_limit}")
    log.info(f"  - document_uploads_enabled: {settings.document_uploads_enabled}")
    log.info(f"  - max_upload_size_mb: {settings.max_upload_size_mb}")
    log.info("")
    log.info("JWT Configuration:")
    log.info(f"  - jwt_lifetime_seconds: {settings.jwt_lifetime_seconds}")
    jwt_secret_value = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
    log.info(
        "  - jwt_secret: "
        f"{'DEFAULT (change in production!)' if jwt_secret_value == 'CHANGE_THIS_IN_PRODUCTION' else 'CONFIGURED'}"
    )
    log.info("")
    log.info("Qdrant Configuration:")
    log.info(f"  - qdrant_url: {settings.qdrant_url}")
    log.info(
        "  - qdrant_api_key: "
        f"{'CONFIGURED' if settings.qdrant_api_key and settings.qdrant_api_key.get_secret_value() else 'NOT SET (local mode)'}"
    )
    log.info("=" * 60)

    toml_dir = Path(__file__).resolve().parent / "config" / "toml"
    toml_snapshot = TOMLSettingsSource(Settings, base_dir=toml_dir, env=settings.env)()

    def describe_source(field_name: str, env_var: str) -> str:
        value = getattr(settings, field_name)
        if env_var and env_var in os.environ:
            return f"{value} (source: environment variable {env_var})"
        if field_name in toml_snapshot and toml_snapshot[field_name] == value:
            return f"{value} (source: TOML base/{settings.env}.toml)"
        default_value = Settings.model_fields[field_name].default
        if value == default_value:
            return f"{value} (source: Settings default)"
        return f"{value} (source: computed)"

    log.info("")
    log.info("Configuration Source Verification:")
    log.info("  Critical settings and resolved sources:")
    for field_name, env_var in [
        ("chat_use_pdf_context", "APP_CHAT_USE_PDF_CONTEXT"),
        ("qdrant_url", "APP_QDRANT_URL"),
        ("llm_model", "APP_LLM_MODEL"),
        ("document_uploads_enabled", "APP_DOCUMENT_UPLOADS_ENABLED"),
        ("pdf_context_limit", "APP_PDF_CONTEXT_LIMIT"),
    ]:
        log.info(f"    - {field_name}: {describe_source(field_name, env_var)}")
    log.info("  Environment variables (APP_*) always override TOML configuration.")
    log.info("=" * 60)

    # Check for environment variable overrides that might conflict with TOML
    env_overrides = []
    tracked_env_vars = [
        "APP_QDRANT_URL",
        "APP_CHAT_USE_PDF_CONTEXT",
        "APP_PDF_CONTEXT_LIMIT",
        "APP_DOCUMENT_UPLOADS_ENABLED",
        "APP_LLM_MODEL",
    ]
    for key in tracked_env_vars:
        if key in os.environ:
            env_overrides.append(f"{key}={os.environ[key]}")

    if env_overrides:
        log.warning("")
        log.warning("⚠️  Environment Variable Overrides Detected:")
        for override in env_overrides:
            log.warning(f"  - {override}")
        log.warning("  These environment variables override TOML configuration.")
        log.warning("  To use TOML values, unset these environment variables.")
        log.warning("")

    if "APP_QDRANT_URL" in os.environ:
        log.warning(
            "APP_QDRANT_URL is set and will override qdrant_url from base/dev TOML files."
        )

    if settings.chat_use_pdf_context and not settings.document_uploads_enabled:
        log.warning(
            "PDF context is enabled but document uploads are disabled - users cannot upload documents!"
        )

    # ========== CRITICAL: Validate Configuration Before Service Initialization ==========
    # This validation MUST happen before any service initialization to ensure
    # clear error messages if configuration is invalid. Services depend on valid config.

    is_production = settings.env.lower() in ("prod", "production")

    log.info("")
    log.info("=" * 60)
    log.info("Configuration Validation (Pre-Service Initialization)")
    log.info("=" * 60)

    # Initialize startup_errors list before any validation
    startup_errors = []

    if is_production:
        log.info("Production environment detected - validating required secrets")
        try:
            # CRITICAL: Validate JWT secret is not default value
            jwt_secret_value = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""
            if jwt_secret_value == "CHANGE_THIS_IN_PRODUCTION":
                log.error("=" * 60)
                log.error("FATAL: Default JWT Secret Detected in Production")
                log.error("=" * 60)
                log.error("JWT secret is set to 'CHANGE_THIS_IN_PRODUCTION'")
                log.error("This allows complete authentication bypass!")
                log.error("Action Required: Set APP_JWT_SECRET to a secure random value")
                log.error("  Generate with: openssl rand -hex 32")
                log.error("=" * 60)
                raise RuntimeError("Production startup aborted: JWT secret not changed from default")

            # SecurityManager validates environment secrets (JWT, database, etc.)
            SecurityManager.validate_env_secrets(require_all_in_production=True)

            # Settings validates application-level secrets (Stripe, etc.)
            is_valid, secret_issues = settings.validate_production_secrets()
            if not is_valid:
                log.error("Additional production configuration validation failed:")
                for issue in secret_issues:
                    log.error(f"  - {issue}")
                    startup_errors.append({"service": "production_secret_validation", "error": issue, "type": "secret"})
                raise RuntimeError(f"Production configuration incomplete: {'; '.join(secret_issues)}")

            log.info("✓ Production secrets validated successfully (JWT secret secure, continuing to validate database configuration...)")

            # Validate subscription fail-open mode in production
            if settings.subscription_fail_open:
                log.warning("")
                log.warning("=" * 60)
                log.warning("⚠️  SECURITY WARNING: Subscription Fail-Open Mode Active")
                log.warning("=" * 60)
                log.warning("  subscription_fail_open=True in production environment")
                log.warning("  This allows requests to proceed when subscription checks fail")
                log.warning("  Recommended: Set APP_SUBSCRIPTION_FAIL_OPEN=false in production")
                log.warning("=" * 60)
                log.warning("")

                # Set Prometheus metric for monitoring
                from app.core.metrics import subscription_fail_open_mode
                subscription_fail_open_mode.set(1)

            # Validate database configuration in production
            from urllib.parse import urlparse
            database_url = settings.database_url.get_secret_value() if settings.database_url else ""
            parsed = urlparse(database_url) if database_url else None
            hostname = parsed.hostname if parsed else None
            scheme = parsed.scheme if parsed else None
            netloc = parsed.netloc if parsed else None

            invalid_local_hosts = {"localhost", "127.0.0.1", "::1"}
            is_sqlite_or_file = (scheme == "sqlite") or (scheme == "file") or (netloc == "")
            is_localhost = hostname in invalid_local_hosts
            is_missing = not database_url

            if is_missing or is_sqlite_or_file or is_localhost:
                log.error("=" * 60)
                log.error("FATAL: Production Database Configuration Invalid")
                log.error("=" * 60)
                if is_missing:
                    log.error("Database URL is not set")
                elif is_sqlite_or_file:
                    log.error("SQLite or file-based database detected - not allowed in production")
                elif is_localhost:
                    log.error(f"Database URL points to local host '{hostname}' - not allowed in production")
                log.error("Action Required: Set APP_DATABASE_URL to a production-grade database (non-localhost, non-sqlite)")
                log.error("=" * 60)
                raise RuntimeError("Production startup aborted: Database not configured for production")

            # Validate Redis configuration if caching enabled
            if settings.redis_enabled and settings.redis_host in ("localhost", "127.0.0.1", "::1"):
                log.warning("=" * 60)
                log.warning("⚠️  WARNING: Redis points to localhost in production")
                log.warning("=" * 60)
                log.warning("  This may cause issues in distributed deployments")
                log.warning("  Consider using APP_REDIS_HOST environment variable")
                log.warning("=" * 60)

            # Final confirmation after all production validations pass
            log.info("✓ All production configuration validations passed (secrets, database, redis)")

        except RuntimeError as e:
            # Fail startup immediately with clear error message
            log.error("=" * 60)
            log.error("FATAL: Production Configuration Validation Failed")
            log.error("=" * 60)
            log.error(f"Reason: {e}")
            log.error("Action Required: Set missing environment variables or check configuration")
            log.error("=" * 60)
            raise RuntimeError(f"Production startup aborted: {e}") from e

        # Set metric to 0 when fail-open is disabled in production
            # (Removed duplicate Prometheus metric setting for subscription_fail_open_mode)
    else:
        log.info(f"Development environment ({settings.env}) - relaxed validation mode")
        # Still validate but only warn on issues in development
        try:
            SecurityManager.validate_env_secrets(require_all_in_production=False)
            log.info("✓ Development configuration validated")
        except Exception as e:
            log.warning(f"⚠ Configuration issues detected in development: {e}")
            log.warning("  These would prevent production startup but are allowed in development")

    log.info("=" * 60)
    log.info("")

    # Initialize shared state for service instances
    app.state.startup_errors = startup_errors
    app.state.serving_enabled = False  # Start pessimistically - only enable when all critical services ready
    app.state.background_tasks = []  # Track all background tasks for graceful shutdown
    app.state.services_ready = {
        "database": False,
        "llm_manager": False,
        "qdrant_manager": False,
        "cache_service": False,  # Non-critical, but tracked
        "prompt_renderer": False,  # Non-critical, but tracked
        "expansion_service": False,  # Non-critical, but tracked
        "chat_history_service": False,  # Non-critical, but tracked
        "chat_qdrant_service": False,  # Non-critical, but tracked
        "paper_workflow": False,  # Non-critical, but tracked
        "review_workflow": False,  # Non-critical, but tracked
        "payment_service": False,  # Non-critical, but tracked
        "subscription_manager": False,  # Non-critical, but tracked
        "billing_service": False,  # Non-critical, but tracked
        "refund_dispute_service": False,  # Non-critical, but tracked
    }

    # Initialize database (CRITICAL - failure aborts startup)
    try:
        await init_db()
        app.state.services_ready["database"] = True
        log.info("Database initialization completed")
    except (ConnectionError, TimeoutError) as e:
        error_msg = f"Database connection failed: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "database"}
        )
        app.state.startup_errors.append({"service": "database", "error": str(e), "type": "connection_error"})
    except Exception as e:
        error_msg = f"Database initialization failed with unexpected error: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "database"}
        )
        app.state.startup_errors.append({"service": "database", "error": str(e), "type": type(e).__name__})

    # ========== SERVICE INITIALIZATION (DEPENDENCY ORDER) ==========
    # CRITICAL: Services must be initialized in this exact order to satisfy dependencies.
    #
    # Dependency Chain:
    #   1. PromptRenderer (no dependencies)
    #   2. RedisCacheService (no dependencies)
    #   3. LLMManager (depends on: PromptRenderer, cache_service)
    #   4. QdrantManager (depends on: LLMManager, cache_service)
    #   5. ExpansionService (depends on: LLMManager, QdrantManager, PromptRenderer)
    #   6. ChatHistoryService (depends on: cache_service)
    #   7. ChatQdrantService (depends on: LLMManager, QdrantManager, cache_service)
    #   8. Workflow Services (depend on above services)
    #
    # IMPORTANT: DO NOT REORDER without updating dependency injection parameters!
    # Cache service must be initialized BEFORE LLMManager and QdrantManager to ensure
    # they receive the correct cache_service instance (or None for graceful degradation).
    # ================================================================

    # Initialize PromptRenderer (STATELESS - no external dependencies)
    try:
        prompt_renderer = await PromptRenderer.start()
        app.state.prompt_renderer = prompt_renderer
        app.state.services_ready["prompt_renderer"] = True
        log.info("PromptRenderer initialized and stored in app state")
    except Exception as e:
        error_msg = f"PromptRenderer initialization failed with unexpected error: {e}"
        log.warning(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "prompt_renderer"}
        )
        app.state.prompt_renderer = None
        # Non-critical service, continue without it

    # Initialize Redis cache service (NON-CRITICAL - graceful degradation)
    # IMPORTANT: Must complete before LLMManager/QdrantManager initialization
    # to ensure they receive the correct cache_service instance (or None)
    try:
        cache_service = await RedisCacheService.start(settings)
        app.state.cache_service = cache_service
        app.state.services_ready["cache_service"] = True
        log.info("RedisCacheService initialized and stored in app state")
    except (ConnectionError, TimeoutError) as e:
        log.warning(
            f"Redis connection failed: {e} - running without cache",
            extra={"error_type": type(e).__name__, "service": "cache_service"}
        )
        app.state.cache_service = None
        # Don't fail startup, just log warning (graceful degradation)
    except Exception as e:
        log.warning(
            f"Redis cache initialization failed with unexpected error: {e} - running without cache",
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "cache_service"}
        )
        app.state.cache_service = None

    # Initialize AuthService (depends on cache_service)
    try:
        auth_service = await AuthService.start(cache_service=app.state.cache_service)
        app.state.auth_service = auth_service
        app.state.services_ready["auth_service"] = True
        log.info("AuthService initialized and stored in app state")
    except Exception as e:
        log.warning(
            f"AuthService initialization failed: {e} - auth features may be limited",
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "auth_service"}
        )
        app.state.auth_service = None

    # Initialize Payment Services (depends on cache_service) - NON-CRITICAL
    # Payment services are initialized conditionally based on payments_enabled setting
    # and provide graceful degradation when payments are disabled or initialization fails
    if settings.payments_enabled:
        try:
            from app.services.payment_service import PaymentService
            from app.services.subscription_manager import SubscriptionManager
            from app.services.billing_service import BillingService
            
            # Initialize PaymentService
            payment_service = await PaymentService.start(
                cache_service=app.state.cache_service
            )
            app.state.payment_service = payment_service
            app.state.services_ready["payment_service"] = True
            log.info("PaymentService initialized and stored in app state")
            
            # Initialize SubscriptionManager (depends on cache_service)
            subscription_manager = await SubscriptionManager.start(
                cache_service=app.state.cache_service
            )
            app.state.subscription_manager = subscription_manager
            app.state.services_ready["subscription_manager"] = True
            log.info("SubscriptionManager initialized and stored in app state")
            
            # Initialize BillingService (depends on cache_service)
            billing_service = await BillingService.start(
                cache_service=app.state.cache_service
            )
            app.state.billing_service = billing_service
            app.state.services_ready["billing_service"] = True
            log.info("BillingService initialized and stored in app state")
            
            # Initialize RefundDisputeService (depends on payment_service and subscription_manager)
            from app.services.refund_dispute_service import RefundDisputeService
            refund_dispute_service = await RefundDisputeService.start(
                payment_service=payment_service,
                subscription_manager=subscription_manager,
                cache_service=app.state.cache_service
            )
            app.state.refund_dispute_service = refund_dispute_service
            app.state.services_ready["refund_dispute_service"] = True
            log.info("RefundDisputeService initialized and stored in app state")
            
            log.info("Payment services initialized successfully")
        except Exception as e:
            log.warning(
                f"Payment services initialization failed: {e} - payments will be disabled",
                exc_info=True,
                extra={"error_type": type(e).__name__, "service": "payment_services"}
            )
            app.state.payment_service = None
            app.state.subscription_manager = None
            app.state.billing_service = None
            app.state.refund_dispute_service = None
            # Non-critical services, continue without them
    else:
        log.info("Payments disabled - skipping payment service initialization")
        app.state.payment_service = None
        app.state.subscription_manager = None
        app.state.billing_service = None
        app.state.refund_dispute_service = None

    # Initialize LLM Manager (CRITICAL - depends on PromptRenderer and uses cache_service)
    try:
        llm_manager = await LLMManager.start(
            settings=settings,
            prompt_renderer=app.state.prompt_renderer,
            cache_service=app.state.cache_service
        )
        app.state.llm_manager = llm_manager
        app.state.services_ready["llm_manager"] = True
        log.info("LLMManager initialized and stored in app state")
    except (ConnectionError, TimeoutError) as e:
        error_msg = f"LLM service connection failed: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "llm_manager"}
        )
        app.state.startup_errors.append({"service": "llm_manager", "error": str(e), "type": "connection_error"})
    except Exception as e:
        error_msg = f"LLMManager initialization failed with unexpected error: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "llm_manager"}
        )
        app.state.startup_errors.append({"service": "llm_manager", "error": str(e), "type": type(e).__name__})

    # Initialize Qdrant Manager (CRITICAL - depends on LLMManager and uses cache_service)
    try:
        qdrant_manager = await QdrantManager.start(
            settings,
            llm_manager=app.state.llm_manager,
            cache_service=app.state.cache_service
        )
        app.state.qdrant_manager = qdrant_manager
        app.state.services_ready["qdrant_manager"] = True
        log.info("QdrantManager initialized and stored in app state")

        # Verify Qdrant collections and log user document collections
        try:
            collections = await qdrant_manager.get_collections()
            collection_names = [c.name for c in collections.collections]

            log.info(f"Qdrant collections available: {len(collection_names)} total")

            philosopher_collections = [
                "Meta Collection", "Combined Collection",
                "Aristotle", "John Locke", "Friedrich Nietzsche",
                "Immanuel Kant", "David Hume"
            ]

            chat_collections = [c for c in collection_names if "Chat_History" in c]

            user_collections = [
                c for c in collection_names
                if c not in philosopher_collections
                and "Chat_History" not in c
            ]

            log.info(
                f"  - Philosopher collections: "
                f"{len([c for c in collection_names if c in philosopher_collections])}"
            )
            log.info(f"  - Chat history collections: {len(chat_collections)}")
            log.info(f"  - User document collections: {len(user_collections)}")

            if user_collections:
                log.info(f"  - User collections found: {user_collections}")
                for user_collection in user_collections:
                    try:
                        collection_info = await qdrant_manager.qclient.get_collection(
                            collection_name=user_collection
                        )
                        point_count = (
                            collection_info.points_count
                            if hasattr(collection_info, "points_count")
                            else "unknown"
                        )
                        log.info(f"    - {user_collection}: {point_count} document chunks")
                    except (ConnectionError, TimeoutError) as e:
                        log.warning(
                            f"    - {user_collection}: Connection error getting point count: {e}",
                            extra={"collection": user_collection, "error_type": type(e).__name__}
                        )
                    except Exception as e:
                        log.warning(
                            f"    - {user_collection}: Unexpected error getting point count: {e}",
                            extra={"collection": user_collection, "error_type": type(e).__name__}
                        )
            else:
                log.info("  - No user document collections found (no documents uploaded yet)")

            if settings.chat_use_pdf_context:
                if not user_collections:
                    log.warning(
                        "PDF context is enabled but no user document collections exist. "
                        "Users need to upload documents via POST /documents/upload"
                    )
                else:
                    log.info(
                        f"PDF context is enabled and {len(user_collections)} user(s) have uploaded documents"
                    )

        except (ConnectionError, TimeoutError) as e:
            log.warning(
                f"Connection error while verifying Qdrant collections: {e}",
                extra={"error_type": type(e).__name__}
            )
        except Exception as e:
            log.warning(
                f"Unexpected error verifying Qdrant collections: {e}",
                exc_info=True,
                extra={"error_type": type(e).__name__}
            )
    except (ConnectionError, TimeoutError) as e:
        error_msg = f"Qdrant service connection failed: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "qdrant_manager"}
        )
        app.state.startup_errors.append({"service": "qdrant_manager", "error": str(e), "type": "connection_error"})
    except Exception as e:
        error_msg = f"QdrantManager initialization failed with unexpected error: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "qdrant_manager"}
        )
        app.state.startup_errors.append({"service": "qdrant_manager", "error": str(e), "type": type(e).__name__})

    # Initialize Expansion Service (depends on LLM + Qdrant + PromptRenderer)
    try:
        expansion_service = await ExpansionService.start(
            llm_manager=app.state.llm_manager,
            qdrant_manager=app.state.qdrant_manager,
            prompt_renderer=app.state.prompt_renderer
        )
        app.state.expansion_service = expansion_service
        app.state.services_ready["expansion_service"] = True
        log.info("ExpansionService initialized and stored in app state")
    except (ConnectionError, TimeoutError) as e:
        error_msg = f"ExpansionService connection failed: {e}"
        log.error(
            error_msg,
            extra={"error_type": type(e).__name__, "service": "expansion_service"}
        )
        app.state.startup_errors.append({"service": "expansion_service", "error": str(e), "type": "connection_error"})
        # ExpansionService failure is non-critical for basic health checks
    except Exception as e:
        error_msg = f"ExpansionService initialization failed with unexpected error: {e}"
        log.error(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "expansion_service"}
        )
        app.state.startup_errors.append({"service": "expansion_service", "error": str(e), "type": type(e).__name__})

    # Initialize ChatHistoryService (depends on cache_service)
    try:
        chat_history_service = await ChatHistoryService.start(
            cache_service=app.state.cache_service
        )
        app.state.chat_history_service = chat_history_service
        app.state.services_ready["chat_history_service"] = True
        log.info("ChatHistoryService initialized and stored in app state")
    except (ConnectionError, TimeoutError) as e:
        error_msg = f"ChatHistoryService connection failed: {e}"
        log.warning(
            error_msg,
            extra={"error_type": type(e).__name__, "service": "chat_history_service"}
        )
        app.state.chat_history_service = None
        # Non-critical service, continue without it
    except Exception as e:
        error_msg = f"ChatHistoryService initialization failed with unexpected error: {e}"
        log.warning(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "chat_history_service"}
        )
        app.state.chat_history_service = None
        # Non-critical service, continue without it

    # Initialize ChatQdrantService (depends on Qdrant + LLM + ExpansionService)
    try:
        chat_qdrant_service = await ChatQdrantService.start(
            qdrant_client=app.state.qdrant_manager.qclient,
            llm_manager=app.state.llm_manager,
            expansion_service=app.state.expansion_service
        )
        app.state.chat_qdrant_service = chat_qdrant_service
        app.state.services_ready["chat_qdrant_service"] = True
        log.info("ChatQdrantService initialized and stored in app state")
    except (ConnectionError, TimeoutError) as e:
        error_msg = f"ChatQdrantService connection failed: {e}"
        log.warning(
            error_msg,
            extra={"error_type": type(e).__name__, "service": "chat_qdrant_service"}
        )
        app.state.chat_qdrant_service = None
        # Non-critical service, continue without it
    except Exception as e:
        error_msg = f"ChatQdrantService initialization failed with unexpected error: {e}"
        log.warning(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "chat_qdrant_service"}
        )
        app.state.chat_qdrant_service = None
        # Non-critical service, continue without it

    # Initialize PaperWorkflow (depends on ExpansionService + LLM + PromptRenderer)
    try:
        paper_workflow = PaperWorkflow(
            expansion_service=app.state.expansion_service,
            llm_manager=app.state.llm_manager,
            prompt_renderer=app.state.prompt_renderer
        )
        app.state.paper_workflow = paper_workflow
        app.state.services_ready["paper_workflow"] = True
        log.info("PaperWorkflow initialized and stored in app state")
    except Exception as e:
        error_msg = f"PaperWorkflow initialization failed with unexpected error: {e}"
        log.warning(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "paper_workflow"}
        )
        app.state.paper_workflow = None
        app.state.startup_errors.append({
            "service": "paper_workflow",
            "error": str(e),
            "type": type(e).__name__
        })
        # Non-critical service, continue without it

    # Initialize ReviewWorkflow (depends on ExpansionService + LLM + PromptRenderer)
    try:
        review_workflow = ReviewWorkflow(
            expansion_service=app.state.expansion_service,
            llm_manager=app.state.llm_manager,
            prompt_renderer=app.state.prompt_renderer
        )
        app.state.review_workflow = review_workflow
        app.state.services_ready["review_workflow"] = True
        log.info("ReviewWorkflow initialized and stored in app state")
    except Exception as e:
        error_msg = f"ReviewWorkflow initialization failed with unexpected error: {e}"
        log.warning(
            error_msg,
            exc_info=True,
            extra={"error_type": type(e).__name__, "service": "review_workflow"}
        )
        app.state.review_workflow = None
        app.state.startup_errors.append({
            "service": "review_workflow",
            "error": str(e),
            "type": type(e).__name__
        })
        # Non-critical service, continue without it

    # Warm cache with frequently accessed data (if enabled and services available)
    if (
        settings.cache_warming_enabled
        and app.state.qdrant_manager
        and app.state.cache_service
        and app.state.llm_manager
    ):
        try:
            log.info(f"Cache warming enabled: {settings.cache_warming_items}")
            cache_warming_service = CacheWarmingService(
                qdrant_manager=app.state.qdrant_manager,
                cache_service=app.state.cache_service,
                llm_manager=app.state.llm_manager,
                enabled=settings.cache_warming_enabled,
                warming_items=settings.cache_warming_items
            )
            warming_results = await cache_warming_service.warm_cache()

            # Log detailed warming results
            if warming_results.get("enabled"):
                stats = warming_results.get("stats", {})
                total_duration = stats.get("total_duration_seconds", 0)
                collections_stats = stats.get("philosopher_collections", {})
                embeddings_stats = stats.get("common_embeddings", {})
                errors = stats.get("errors", [])

                log.info(f"Cache warming completed in {total_duration:.2f}s")

                if collections_stats.get("success"):
                    log.info(
                        f"  - Collections: {collections_stats.get('items_warmed', 0)} items "
                        f"in {collections_stats.get('duration_seconds', 0):.2f}s"
                    )

                if embeddings_stats.get("success"):
                    log.info(
                        f"  - Embeddings: {embeddings_stats.get('items_warmed', 0)} items "
                        f"in {embeddings_stats.get('duration_seconds', 0):.2f}s"
                    )

                if errors:
                    log.warning(f"Cache warming errors: {errors}")
            else:
                log.info("Cache warming disabled via configuration")
        except Exception as e:
            log.warning(f"Cache warming failed (non-critical): {e}", exc_info=True)
    else:
        log.info("Cache warming skipped: required services not available")

    # ATOMIC CHECK: Only enable serving when ALL critical services are ready
    critical_services = ["database", "llm_manager", "qdrant_manager"]
    all_critical_ready = all(
        app.state.services_ready.get(svc, False) for svc in critical_services
    )

    if all_critical_ready:
        app.state.serving_enabled = True
        log.info("All critical services initialized successfully")
    else:
        failed_services = [
            svc for svc in critical_services
            if not app.state.services_ready.get(svc, False)
        ]
        log.error(f"Startup failed due to critical service errors: {failed_services}")
        log.error(f"Detailed errors: {app.state.startup_errors}")
        log.error("Application will serve health endpoints only until critical services are restored")

        log.info("")
        log.info("=" * 60)
        log.info("Ontologic API Ready")
        log.info("=" * 60)
        log.info(f"Environment: {settings.env}")
        log.info(f"PDF Context: {'ENABLED' if settings.chat_use_pdf_context else 'DISABLED'}")
        log.info(
            f"Document Uploads: {'ENABLED' if settings.document_uploads_enabled else 'DISABLED'}"
        )
        log.info(f"Chat History: {'ENABLED' if settings.chat_history else 'DISABLED'}")
        log.info(f"Qdrant: {settings.qdrant_url}")
        log.info("=" * 60)
        log.info("")

    # Initialize custom Prometheus metrics
    try:
        from app.core.metrics import initialize_metrics, log_metrics_summary
        initialize_metrics(
            version="1.0.0",
            environment=settings.env
        )
        log_metrics_summary()
    except Exception as e:
        log.warning(f"Failed to initialize custom metrics: {e}", exc_info=True)

    # Start background task for periodic metrics updates
    async def update_metrics_periodically():
        """Background task to update cache and Qdrant metrics every 60 seconds."""
        import asyncio
        while True:
            try:
                await asyncio.sleep(60)  # Update every 60 seconds

                # Update cache metrics
                if app.state.cache_service:
                    try:
                        await app.state.cache_service.update_metrics()
                    except Exception as e:
                        log.debug(f"Cache metrics update failed: {e}")

                # Update Qdrant collection metrics
                if app.state.qdrant_manager:
                    try:
                        await app.state.qdrant_manager.update_collection_metrics()
                    except Exception as e:
                        log.debug(f"Qdrant metrics update failed: {e}")

            except asyncio.CancelledError:
                log.info("Metrics update task cancelled")
                break
            except Exception as e:
                log.warning(f"Metrics update task error: {e}", exc_info=True)

    # Start the background task if serving is enabled
    if app.state.serving_enabled:
        import asyncio
        if not hasattr(app.state, 'background_tasks'):
            app.state.background_tasks = []

        metrics_task = asyncio.create_task(update_metrics_periodically())
        app.state.background_tasks.append(metrics_task)
        app.state.metrics_task = metrics_task
        log.info("Started background metrics update task (60s interval)")

    # Log subscription middleware status (middleware is added during configure_app)
    if settings.payments_enabled:
        if app.state.subscription_manager:
            log.info("SubscriptionMiddleware active with payment services")
        else:
            log.warning("Payments enabled but SubscriptionManager not available - subscription middleware will be inactive")
    else:
        log.info("Payments disabled - subscription middleware inactive")

    log.info("Ontologic API startup complete with modern lifespan management")

    # Yield control to the application
    yield
    
    # ========== SHUTDOWN ==========
    log.info("Shutting down Ontologic API with proper async cleanup...")

    # Cancel all background tasks with timeout
    import asyncio
    background_tasks = getattr(app.state, 'background_tasks', [])

    # Add metrics task to the list if it exists and isn't already tracked
    metrics_task = getattr(app.state, 'metrics_task', None)
    if metrics_task and metrics_task not in background_tasks:
        background_tasks.append(metrics_task)

    if background_tasks:
        log.info(f"Cancelling {len(background_tasks)} background task(s)...")
        cancelled_count = 0

        for task in background_tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1

        # Wait for all tasks to finish cancellation with timeout
        if cancelled_count > 0:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*background_tasks, return_exceptions=True),
                    timeout=10.0  # 10 second timeout for graceful cancellation
                )
                log.info(f"Successfully cancelled {cancelled_count} background task(s)")
            except asyncio.TimeoutError:
                log.warning(f"Background task cancellation timed out after 10s")
            except Exception as e:
                log.error(f"Error during background task cancellation: {e}")
    else:
        log.info("No background tasks to cancel")

    # Shutdown OpenTelemetry tracing (flush pending spans)
    try:
        from app.core.tracing import TracingConfig
        TracingConfig.shutdown()
    except Exception as e:
        log.warning(f"Failed to shutdown tracing: {e}")

    # Close services in reverse dependency order
    services = [
        ('review_workflow', 'ReviewWorkflow'),
        ('paper_workflow', 'PaperWorkflow'),
        ('chat_qdrant_service', 'ChatQdrantService'),
        ('chat_history_service', 'ChatHistoryService'),
        ('expansion_service', 'ExpansionService'),
        ('refund_dispute_service', 'RefundDisputeService'),
        ('billing_service', 'BillingService'),
        ('subscription_manager', 'SubscriptionManager'),
        ('payment_service', 'PaymentService'),
        ('cache_service', 'RedisCacheService'),
        ('qdrant_manager', 'QdrantManager'),
        ('llm_manager', 'LLMManager'),
        ('prompt_renderer', 'PromptRenderer')
    ]
    
    for service_name, service_type in services:
        try:
            service = getattr(app.state, service_name, None)
            if service is not None and hasattr(service, 'aclose'):
                await service.aclose()
                log.info(f"{service_type} cleaned up")
            elif service is not None and hasattr(service, 'shutdown'):
                service.shutdown()  # Fallback for sync cleanup
                log.info(f"{service_type} shutdown completed")
            else:
                log.info(f"No {service_type} instance to clean up")
        except Exception as e:
            log.warning(f"Failed to clean up {service_type}: {e}", exc_info=True)
    
    log.info("Ontologic API shutdown complete")


# Module-level app instance for uvicorn app.main:app
app = FastAPI(
    title="Ontologic API",
    version="1.0.0",
    lifespan=lifespan
)

# Configure the module-level app instance after startup
def configure_app():
    """Configure the app with routers and middleware after environment is set."""
    from app.router import router
    from app.core.rate_limiting import limiter
    from app.config import get_trusted_hosts, get_cors_config
    from app.config.settings import get_settings

    # Get settings for middleware configuration
    settings = get_settings()

    # Import the shared limiter and attach to app state
    app.state.limiter = limiter

    # Add subscription middleware for access control and usage tracking
    # This middleware gets services dynamically from app.state during request processing
    from app.core.subscription_middleware import SubscriptionMiddleware
    app.add_middleware(
        SubscriptionMiddleware,
        subscription_manager=None,  # Will be retrieved from app.state
        billing_service=None,       # Will be retrieved from app.state
        auth_service=None,          # Will be retrieved from app.state
        enabled=getattr(settings, 'payments_enabled', False)
    )
    
    # Add SlowAPI middleware
    app.add_middleware(SlowAPIMiddleware)

    # Custom rate limit exceeded handler with logging
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request, exc):
        from slowapi.util import get_remote_address
        from app.core.logger import log
        client_ip = get_remote_address(request)
        endpoint = request.url.path
        log.warning(f"Rate limit exceeded for IP {client_ip} on endpoint {endpoint}")
        return _rate_limit_exceeded_handler(request, exc)

    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # Load trusted hosts from configuration
    trusted_hosts = get_trusted_hosts()
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=trusted_hosts
    )
    from app.core.logger import log
    log.info(f"TrustedHostMiddleware configured with hosts: {trusted_hosts}")

    # Load CORS configuration with production restrictions
    if settings.env.lower() in ("prod", "production"):
        # In production, require explicit origin list from Settings (already parsed and validated)
        if settings.cors_origins:
            allowed_origins = settings.cors_origins
        else:
            # Fail startup immediately when CORS is not configured in production
            log.error("=" * 60)
            log.error("FATAL: Production CORS Configuration Missing")
            log.error("=" * 60)
            log.error("APP_CORS_ORIGINS environment variable is not set")
            log.error("Action Required: Set APP_CORS_ORIGINS with comma-separated allowed origins")
            log.error("Example: APP_CORS_ORIGINS='https://app.example.com,https://www.example.com'")
            log.error("=" * 60)
            raise RuntimeError("Production startup aborted: APP_CORS_ORIGINS not configured")
    else:
        # Development: allow localhost
        allowed_origins = [
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8080"
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    log.info(f"CORS configured with {len(allowed_origins)} allowed origins: {allowed_origins}")

    # Add GZip compression middleware (2025 FastAPI best practice)
    # Conditionally enabled based on configuration
    if settings.compression_enabled:
        app.add_middleware(
            GZipMiddleware,
            minimum_size=settings.compression_minimum_size
        )
        log.info(
            f"GZipMiddleware enabled with minimum_size={settings.compression_minimum_size} bytes "
            f"(responses smaller than this will not be compressed)"
        )
    else:
        log.info("GZipMiddleware disabled via configuration (compression_enabled=False)")

    # Initialize Prometheus metrics instrumentation
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics"],
        env_var_name="ENABLE_METRICS",
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    )
    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    log.info("Prometheus metrics instrumentation enabled at /metrics endpoint")
    log.info("Custom application metrics: LLM latency, cache hit rates, Qdrant query performance")

    # Initialize OpenTelemetry tracing
    from app.core.tracing import TracingConfig
    TracingConfig.initialize(
        service_name="ontologic-api",
        service_version="1.0.0",
        enabled=True,  # Can be disabled via OTEL_ENABLED=false env var
        export_to_console=False,  # Set OTEL_EXPORT_CONSOLE=true for debugging
        otlp_endpoint=None  # Set OTEL_EXPORTER_OTLP_ENDPOINT for production
    )
    TracingConfig.instrument_fastapi(app)

    # Apply security headers to all responses (including health checks and errors)
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        """
        Apply security headers to all responses.

        Headers are applied to all endpoints including health checks, errors,
        and normal responses. Uses SecurityManager.get_security_headers() as
        single source of truth for security header configuration.
        """
        # Import SecurityManager within function scope
        from app.core.security import SecurityManager

        # Process the request
        response = await call_next(request)

        # Get security headers from SecurityManager
        security_headers = SecurityManager.get_security_headers()

        # Apply each header to the response
        for header_name, header_value in security_headers.items():
            response.headers[header_name] = header_value

        return response

    # Add middleware to check startup state before serving traffic
    @app.middleware("http")
    async def startup_check_middleware(request: Request, call_next):
        """
        Middleware to check if critical services are available.
        Returns 503 for non-health endpoints if startup failed.
        """
        # Allow health endpoints always (for monitoring during startup issues)
        if request.url.path.startswith("/health"):
            return await call_next(request)
        
        # Check if serving is enabled (critical services are up)
        serving_enabled = getattr(app.state, 'serving_enabled', True)
        startup_errors = getattr(app.state, 'startup_errors', [])
        
        if not serving_enabled and startup_errors:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Service Unavailable",
                    "message": "Critical services are unavailable. Server cannot serve traffic.",
                    "startup_errors": startup_errors,
                    "health_check": "/health"
                }
            )
        
        return await call_next(request)
    
    # Include routers
    app.include_router(router)

# Configure app immediately (will fail if no QDRANT_API_KEY, but that's expected in dev)
try:
    configure_app()
    app._configured = True
except Exception as e:
    # Store configuration error for debugging
    app._configured = False
    app._config_error = e
    # Note: Can't use log here as it's not imported at module level
    print(f"Warning: Initial app configuration failed: {e}")
    print("App will be configured during _main() when environment is properly set")


def _main(app_env="DEV", host="0.0.0.0", port=8080, log_level="info", reload=True):
    os.environ["APP_ENV"] = app_env
    os.environ["LOG_LEVEL"] = log_level.upper()
    
    from app.core.logger import log, log_config
    
    # Ensure app is configured (in case module-level configuration failed)
    if not getattr(app, '_configured', False):
        try:
            configure_app()
            app._configured = True
            log.info("App configuration completed successfully")
        except Exception as e:
            config_error = getattr(app, '_config_error', None)
            log.error(f"Fatal: App configuration failed during _main(): {e}", exc_info=True)
            if config_error:
                log.error(f"Previous configuration error: {config_error}")
            log.error("Cannot start server without proper configuration")
            raise SystemExit(1) from e
    
    log.info("Rate limiting enabled with IP-based tracking")
    log.info("CORS configured with restricted methods and headers")
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        reload=reload,
        timeout_keep_alive=UVICORN_KEEPALIVE_TIMEOUT_SECONDS,
        timeout_graceful_shutdown=UVICORN_GRACEFUL_SHUTDOWN_SECONDS,
        log_config=log_config
    )


    server = uvicorn.Server(config)
    server.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FastAPI application.")
    parser.add_argument(
        "--env", default="dev", help="Set the application environment (e.g., dev, prod)"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Set the server host")
    parser.add_argument("-p", "--port", type=int, default=8080, help="Set the server port")
    parser.add_argument(
        "--log-level",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        default="info",
        help="Set the logging level",
    )
    parser.add_argument(
        "--no-reload", action="store_true", help="Disable automatic reloading"
    )

    args = parser.parse_args()
    _main(
        app_env=args.env,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=not args.no_reload,
    )
