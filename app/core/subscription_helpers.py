"""
Subscription enforcement and usage tracking helpers.

Provides reusable functions for subscription-based access control and usage tracking
across API endpoints, reducing code duplication and ensuring consistent behavior.
"""

import math
from typing import Optional
from fastapi import Request, HTTPException
from app.core.user_models import User
from app.core.dependencies import SubscriptionManagerDep
from app.config.settings import get_settings
from app.core.error_responses import create_authorization_error
from app.core.logger import log
from app.core.constants import CHARS_PER_TOKEN_ESTIMATE


async def check_subscription_access(
    user: Optional[User],
    subscription_manager: SubscriptionManagerDep,
    endpoint: str,
    request: Request,
) -> None:
    """
    Enforce subscription-based access control for an endpoint.

    Checks if the user's subscription tier allows access to the specified endpoint.
    By default (fail-closed), raises HTTP 503 if subscription check fails. Can be
    configured to fail-open via settings.subscription_fail_open for graceful degradation.

    Args:
        user: Authenticated user (None for anonymous requests)
        subscription_manager: Subscription manager service
        endpoint: API endpoint path (e.g., "/ask", "/ask_philosophy")
        request: FastAPI request object for request_id extraction

    Raises:
        HTTPException: 403 if user lacks access to the endpoint
        HTTPException: 503 if subscription check fails and fail-closed mode is enabled
    """
    settings = get_settings()

    # Skip check if payments disabled or no user/manager
    if not settings.payments_enabled or not subscription_manager or not user:
        return

    try:
        # Check API access before processing request
        has_access = await subscription_manager.check_api_access(user.id, endpoint)
        if not has_access:
            error = create_authorization_error(
                message="Your subscription tier does not allow access to this endpoint",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=403, detail=error.model_dump())
    except HTTPException:
        # Re-raise access denied errors
        raise
    except Exception as e:
        log.error(
            f"Subscription access check failed for user {user.id} on {endpoint}: {e}",
            exc_info=True,
            extra={
                "user_id": user.id,
                "endpoint": endpoint,
                "error_type": type(e).__name__,
                "fail_open_mode": settings.subscription_fail_open
            }
        )
        # Defensive metric recording - don't let monitoring break graceful degradation
        from app.services.monitoring_helpers import safe_record_metric
        safe_record_metric(
            "subscription_check_failures",
            labels={"endpoint": endpoint, "error_type": type(e).__name__}
        )

        # Check fail-open configuration
        if not settings.subscription_fail_open:
            # Fail-closed: raise HTTP 503 error with authorization error structure
            error = create_authorization_error(
                message="Subscription service temporarily unavailable. Please try again.",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=503, detail=error.model_dump())
        # Fail-open: continue processing (graceful degradation)


async def _track_usage_internal(
    user: Optional[User],
    subscription_manager: SubscriptionManagerDep,
    endpoint: str,
    tokens_used: int,
) -> None:
    """
    Internal helper for tracking API usage with pre-calculated tokens.

    Args:
        user: Authenticated user (None for anonymous requests)
        subscription_manager: Subscription manager service
        endpoint: API endpoint path
        tokens_used: Pre-calculated token count
    """
    settings = get_settings()

    # Skip tracking if payments disabled or no user/manager
    if not settings.payments_enabled or not subscription_manager or not user:
        return

    try:
        await subscription_manager.track_api_usage(
            user_id=user.id,
            endpoint=endpoint,
            tokens_used=max(0, int(tokens_used))
        )
    except Exception as e:
        log.warning(
            f"Failed to track usage for user {user.id} on {endpoint}: {e}",
            extra={
                "user_id": user.id,
                "endpoint": endpoint,
                "error_type": type(e).__name__,
                "non_fatal": True
            }
        )
        # Track failure metric with graceful degradation
        from app.services.monitoring_helpers import safe_record_metric
        safe_record_metric(
            "subscription_tracking_failures",
            labels={"endpoint": endpoint, "error_type": type(e).__name__}
        )
        # Non-fatal: continue even if usage tracking fails


async def track_subscription_usage(
    user: Optional[User],
    subscription_manager: SubscriptionManagerDep,
    endpoint: str,
    response_text: str,
) -> None:
    """
    Track API usage for subscription billing from response text.

    Estimates token count using ceiling division with minimum 1 token for non-empty
    responses. Degrades gracefully on failure.

    Args:
        user: Authenticated user (None for anonymous requests)
        subscription_manager: Subscription manager service
        endpoint: API endpoint path (e.g., "/ask", "/ask_philosophy")
        response_text: Response content for token estimation
    """
    # Estimate tokens from text
    estimated_tokens = (
        max(1, math.ceil(len(response_text) / CHARS_PER_TOKEN_ESTIMATE))
        if response_text else 0
    )
    await _track_usage_internal(user, subscription_manager, endpoint, estimated_tokens)


async def track_subscription_tokens(
    user: Optional[User],
    subscription_manager: SubscriptionManagerDep,
    endpoint: str,
    tokens_used: int,
) -> None:
    """
    Track API usage for subscription billing using pre-calculated token count.

    Use this when you have an accurate token count to avoid string construction.
    Degrades gracefully on failure.

    Args:
        user: Authenticated user (None for anonymous requests)
        subscription_manager: Subscription manager service
        endpoint: API endpoint path (e.g., "/documents/upload")
        tokens_used: Number of tokens consumed
    """
    await _track_usage_internal(user, subscription_manager, endpoint, tokens_used)
