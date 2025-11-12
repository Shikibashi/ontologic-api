"""FastAPI dependency providers using lifespan-managed services from app.state."""

from typing import Annotated, TYPE_CHECKING, Any
from fastapi import Depends, Request
from app.core.logger import log

# Type checking imports to avoid circular dependencies
if TYPE_CHECKING:
    from app.core.user_models import User


def get_llm_manager(request: Request):
    """Get LLMManager instance from app.state."""
    llm_manager = getattr(request.app.state, "llm_manager", None)
    if llm_manager is None:
        raise RuntimeError("LLMManager not available - check startup logs")
    return llm_manager


def get_cache_service(request: Request):
    """Get RedisCacheService instance from app.state."""
    return getattr(
        request.app.state, "cache_service", None
    )  # Can be None (graceful degradation)


def get_auth_service(request: Request):
    """Get AuthService instance from app.state."""
    return getattr(
        request.app.state, "auth_service", None
    )  # Can be None (auth features disabled)


def get_chat_history_service(request: Request):
    """Get ChatHistoryService instance from app.state."""
    chat_history_service = getattr(request.app.state, "chat_history_service", None)
    if chat_history_service is None:
        startup_errors = getattr(request.app.state, "startup_errors", [])

        # Check if there's a specific error for this service
        service_errors = [err for err in startup_errors if err.get("service") == "chat_history_service"]

        if service_errors:
            error_detail = service_errors[0].get("error", "Unknown error")
            raise RuntimeError(
                f"ChatHistoryService failed to initialize: {error_detail}. "
                "Check startup logs for details."
            )
        else:
            raise RuntimeError(
                "ChatHistoryService not available - service may be disabled or failed to start. "
                "Check startup logs for details."
            )
    return chat_history_service


def get_chat_qdrant_service(request: Request):
    """Get ChatQdrantService instance from app.state."""
    chat_qdrant_service = getattr(request.app.state, "chat_qdrant_service", None)
    if chat_qdrant_service is None:
        startup_errors = getattr(request.app.state, "startup_errors", [])

        service_errors = [err for err in startup_errors if err.get("service") == "chat_qdrant_service"]

        if service_errors:
            error_detail = service_errors[0].get("error", "Unknown error")
            raise RuntimeError(
                f"ChatQdrantService failed to initialize: {error_detail}. "
                "Check startup logs for details."
            )
        else:
            raise RuntimeError(
                "ChatQdrantService not available - service may be disabled or failed to start. "
                "Check startup logs for details."
            )
    return chat_qdrant_service


def get_prompt_renderer(request: Request):
    """Get PromptRenderer instance from app.state."""
    prompt_renderer = getattr(request.app.state, "prompt_renderer", None)
    if prompt_renderer is None:
        raise RuntimeError("PromptRenderer not available - check startup logs")
    return prompt_renderer


def get_qdrant_manager(request: Request):
    """Get QdrantManager instance from app.state."""
    qdrant_manager = getattr(request.app.state, "qdrant_manager", None)
    if qdrant_manager is None:
        raise RuntimeError("QdrantManager not available - check startup logs")
    return qdrant_manager


def get_expansion_service(request: Request):
    """Get ExpansionService instance from app.state."""
    expansion_service = getattr(request.app.state, "expansion_service", None)
    if expansion_service is None:
        raise RuntimeError("ExpansionService not available - check startup logs")
    return expansion_service


def get_paper_workflow(request: Request):
    """Get PaperWorkflow instance from app.state."""
    paper_workflow = getattr(request.app.state, "paper_workflow", None)
    if paper_workflow is None:
        raise RuntimeError("PaperWorkflow not available - check startup logs")
    return paper_workflow


def get_review_workflow(request: Request):
    """Get ReviewWorkflow instance from app.state."""
    review_workflow = getattr(request.app.state, "review_workflow", None)
    if review_workflow is None:
        raise RuntimeError("ReviewWorkflow not available - check startup logs")
    return review_workflow


def get_payment_service(request: Request):
    """Get PaymentService instance from app.state."""
    return getattr(request.app.state, "payment_service", None)


def get_subscription_manager(request: Request):
    """Get SubscriptionManager instance from app.state."""
    return getattr(request.app.state, "subscription_manager", None)


def get_billing_service(request: Request):
    """Get BillingService instance from app.state."""
    return getattr(request.app.state, "billing_service", None)


async def get_current_user_subscription(
    request: Request,
    subscription_manager = Depends(get_subscription_manager)
):
    """Get current user's subscription information."""
    if not subscription_manager:
        return None
    
    # Try to get user ID from request context
    # This would integrate with your existing authentication system
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return None
        
    return await subscription_manager.get_user_subscription(user_id)


def require_documents_enabled() -> None:
    """
    Dependency guard to ensure document operations are enabled.

    Raises HTTP 503 if document_uploads_enabled=False to prevent unauthenticated
    document access in production environments.

    Usage:
        @router.post("/upload")
        async def upload(..., _: None = Depends(require_documents_enabled)):
            ...

    Raises:
        HTTPException: 503 if document uploads are disabled
    """
    from app.config.settings import get_settings
    from fastapi import HTTPException

    settings = get_settings()
    if not settings.document_uploads_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Document uploads are temporarily disabled. "
                "Contact administrator for access. "
                "(Reason: Authentication implementation required for production use)"
            ),
        )


# Type aliases for dependency injection
LLMManagerDep = Annotated[object, Depends(get_llm_manager)]
QdrantManagerDep = Annotated[object, Depends(get_qdrant_manager)]
CacheServiceDep = Annotated[object, Depends(get_cache_service)]
AuthServiceDep = Annotated[object, Depends(get_auth_service)]
ChatHistoryServiceDep = Annotated[object, Depends(get_chat_history_service)]
ChatQdrantServiceDep = Annotated[object, Depends(get_chat_qdrant_service)]
ExpansionServiceDep = Annotated[object, Depends(get_expansion_service)]
PaperWorkflowDep = Annotated[object, Depends(get_paper_workflow)]
ReviewWorkflowDep = Annotated[object, Depends(get_review_workflow)]
PromptRendererDep = Annotated[object, Depends(get_prompt_renderer)]
PaymentServiceDep = Annotated[object, Depends(get_payment_service)]
SubscriptionManagerDep = Annotated[object, Depends(get_subscription_manager)]
BillingServiceDep = Annotated[object, Depends(get_billing_service)]


def reset_dependency_cache() -> None:
    """No-op for lifespan-managed dependencies. Kept for backward compatibility."""
    log.info("reset_dependency_cache() is no-op with lifespan management")
