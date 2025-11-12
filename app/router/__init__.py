from fastapi import APIRouter
from .ontologic import router as ontologic_router
from .workflows import router as workflows_router
from .health import router as health_router
from .backup_router import backup_router
from .documents import router as documents_router
from .users import router as users_router
from app.config import get_oauth_enabled, get_chat_history_enabled
from app.config.settings import get_settings

router = APIRouter()
# Health check endpoints (always included)
router.include_router(health_router)

# Authentication endpoints (JWT-based user management)
router.include_router(users_router)

router.include_router(ontologic_router)
router.include_router(workflows_router)

# Backup endpoints (for development environment setup)
router.include_router(backup_router)

# Document upload/management endpoints
router.include_router(documents_router, prefix="/documents", tags=["documents"])

# Conditionally include auth router if OAuth features are enabled
if get_oauth_enabled() or get_chat_history_enabled():
    from .auth import router as auth_router
    router.include_router(auth_router)

# Conditionally include chat history router if chat history is enabled
if get_chat_history_enabled():
    from .chat_history import router as chat_history_router
    from .chat_config import router as chat_config_router
    from .chat_health import router as chat_health_router
    router.include_router(chat_history_router)
    router.include_router(chat_config_router)
    router.include_router(chat_health_router)

# Conditionally include payment router if payments are enabled
settings = get_settings()
if settings.payments_enabled:
    from .payments import router as payments_router
    from .admin_payments import router as admin_payments_router
    router.include_router(payments_router)
    router.include_router(admin_payments_router)