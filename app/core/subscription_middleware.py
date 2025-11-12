"""
Subscription-based access control middleware.

Provides middleware for subscription validation, usage tracking, and access control
integration with existing authentication and rate limiting infrastructure.
"""

import time
from datetime import datetime
from typing import Callable, Optional, Dict, Any
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import log
from app.core.db_models import SubscriptionTier, SubscriptionStatus
from app.core.user_models import User
from app.services.subscription_manager import SubscriptionManager, UsageLimitExceededException
from app.services.billing_service import BillingService
from app.services.auth_service import AuthService


class SubscriptionMiddleware(BaseHTTPMiddleware):
    """
    Middleware for subscription-based access control and usage tracking.

    Integrates with existing authentication middleware to provide:
    - Subscription status validation
    - Usage limit enforcement
    - Automatic API usage tracking
    - Proper error responses for exceeded limits

    This middleware works alongside existing authentication and rate limiting
    to provide comprehensive access control based on subscription tiers.
    """

    def __init__(
        self,
        app,
        subscription_manager: Optional[SubscriptionManager] = None,
        billing_service: Optional[BillingService] = None,
        auth_service: Optional[AuthService] = None,
        enabled: bool = True
    ):
        """
        Initialize subscription middleware.

        Args:
            app: FastAPI application instance
            subscription_manager: SubscriptionManager service instance
            billing_service: BillingService for usage tracking
            auth_service: AuthService for user context
            enabled: Whether subscription checking is enabled
        """
        super().__init__(app)
        self.subscription_manager = subscription_manager
        self.billing_service = billing_service
        self.auth_service = auth_service
        self.enabled = enabled
        
        # Endpoints that require subscription validation
        self.protected_endpoints = {
            "/ask": {"tier": SubscriptionTier.FREE, "track_usage": True},
            "/ask/stream": {"tier": SubscriptionTier.FREE, "track_usage": True},
            "/ask_philosophy": {"tier": SubscriptionTier.BASIC, "track_usage": True},
            "/ask_philosophy/stream": {"tier": SubscriptionTier.BASIC, "track_usage": True},
            "/query_hybrid": {"tier": SubscriptionTier.FREE, "track_usage": True},
            "/chat": {"tier": SubscriptionTier.BASIC, "track_usage": True},
            "/documents/upload": {"tier": SubscriptionTier.BASIC, "track_usage": False},
            "/analytics": {"tier": SubscriptionTier.PREMIUM, "track_usage": False},
            "/bulk-export": {"tier": SubscriptionTier.PREMIUM, "track_usage": False},
        }
        
        # Endpoints to exclude from any processing
        self.excluded_endpoints = {
            "/health", "/docs", "/redoc", "/openapi.json",
            "/auth", "/payments/webhooks", "/favicon.ico"
        }

        if not enabled:
            log.info("SubscriptionMiddleware initialized but disabled")
        elif not subscription_manager:
            log.warning("SubscriptionMiddleware initialized without SubscriptionManager - subscription checks disabled")
        else:
            log.info("SubscriptionMiddleware initialized and enabled")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request through subscription middleware.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response
        """
        # Get services dynamically from app.state
        subscription_manager = getattr(request.app.state, 'subscription_manager', None)
        billing_service = getattr(request.app.state, 'billing_service', None)
        auth_service = getattr(request.app.state, 'auth_service', None)
        
        # Skip processing if middleware is disabled or no subscription manager
        if not self.enabled or not subscription_manager:
            return await call_next(request)

        # Skip excluded endpoints
        if self._is_excluded_endpoint(request.url.path):
            return await call_next(request)

        # Get endpoint configuration
        endpoint_config = self._get_endpoint_config(request.url.path)
        if not endpoint_config:
            # Endpoint not protected, continue normally
            return await call_next(request)

        start_time = time.time()
        user_id = None
        subscription_tier = SubscriptionTier.FREE

        try:
            # Get user context from request
            user_context = await self._get_user_context(request, auth_service)
            user_id = user_context.get("user_id")
            
            # If no user context, treat as anonymous free tier user
            if not user_id:
                user_id = self._get_anonymous_user_id(request)
                subscription_tier = SubscriptionTier.FREE
            else:
                # Get user's subscription tier
                subscription_tier = await subscription_manager.get_user_tier(user_id)

            # Store subscription tier in request state for rate limiting
            request.state.subscription_tier = subscription_tier
            request.state.user_id = user_id

            # Check subscription access for endpoint
            required_tier = endpoint_config["tier"]
            if not self._has_tier_access(subscription_tier, required_tier):
                log.warning(f"User {user_id} with tier {subscription_tier} denied access to {request.url.path} (requires {required_tier})")
                return self._create_subscription_required_response(required_tier)

            # Check and enforce rate limits
            try:
                rate_limit_ok = await subscription_manager.enforce_rate_limits(
                    user_id, request.url.path
                )
                if not rate_limit_ok:
                    log.warning(f"Rate limit exceeded for user {user_id} on {request.url.path}")
                    return self._create_rate_limit_response()
            except UsageLimitExceededException as e:
                log.warning(f"Usage limit exceeded for user {user_id}: {e}")
                return self._create_usage_limit_response(str(e))

            # Process the request
            response = await call_next(request)

            # Track usage if enabled for this endpoint
            if endpoint_config.get("track_usage", False) and billing_service:
                await self._track_request_usage(
                    user_id=user_id,
                    endpoint=request.url.path,
                    method=request.method,
                    subscription_tier=subscription_tier,
                    request_duration_ms=int((time.time() - start_time) * 1000),
                    response_status=response.status_code,
                    billing_service=billing_service
                )

            return response

        except Exception as e:
            log.error(f"Error in subscription middleware: {e}", exc_info=True)
            # Don't block requests on middleware errors, just log and continue
            return await call_next(request)

    def _is_excluded_endpoint(self, path: str) -> bool:
        """Check if endpoint should be excluded from subscription processing."""
        for excluded in self.excluded_endpoints:
            if path.startswith(excluded):
                return True
        return False

    def _get_endpoint_config(self, path: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a protected endpoint."""
        # Direct match first
        if path in self.protected_endpoints:
            return self.protected_endpoints[path]
        
        # Check for prefix matches
        for endpoint_pattern, config in self.protected_endpoints.items():
            if path.startswith(endpoint_pattern):
                return config
        
        return None

    async def _get_user_context(self, request: Request, auth_service: Optional[AuthService] = None) -> Dict[str, Any]:
        """Get user context from request."""
        if not auth_service:
            return {}

        # Try to get session ID from various sources
        session_id = None
        
        # Check Authorization header for session ID
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_id = auth_header[7:]  # Remove "Bearer " prefix
        
        # Check X-Session-ID header
        if not session_id:
            session_id = request.headers.get("X-Session-ID")
        
        # Check cookies
        if not session_id:
            session_id = request.cookies.get("session_id")

        if session_id:
            return await auth_service.get_user_context(session_id)
        
        return {}

    def _get_anonymous_user_id(self, request: Request) -> str:
        """Generate anonymous user ID for tracking purposes."""
        # Use client IP as anonymous identifier
        client_ip = request.client.host if request.client else "unknown"
        return f"anon_{hash(client_ip) % 1000000}"

    def _has_tier_access(self, user_tier: SubscriptionTier, required_tier: SubscriptionTier) -> bool:
        """Check if user's tier has access to required tier."""
        tier_hierarchy = {
            SubscriptionTier.FREE: 0,
            SubscriptionTier.BASIC: 1,
            SubscriptionTier.PREMIUM: 2,
            SubscriptionTier.ACADEMIC: 2,  # Academic has same level as Premium
        }
        
        user_level = tier_hierarchy.get(user_tier, 0)
        required_level = tier_hierarchy.get(required_tier, 0)
        
        return user_level >= required_level

    def _create_subscription_required_response(self, required_tier: SubscriptionTier) -> JSONResponse:
        """Create response for subscription required error."""
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "error": "subscription_required",
                "message": f"This endpoint requires a {required_tier.value} subscription or higher.",
                "required_tier": required_tier.value,
                "upgrade_url": "/payments/checkout",
                "details": {
                    "error_code": "SUBSCRIPTION_REQUIRED",
                    "endpoint_access": f"Requires {required_tier.value} tier or higher"
                }
            }
        )

    def _create_rate_limit_response(self) -> JSONResponse:
        """Create response for rate limit exceeded."""
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "rate_limit_exceeded",
                "message": "Rate limit exceeded for your subscription tier. Please try again later.",
                "retry_after": 60,
                "details": {
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "suggestion": "Upgrade your subscription for higher rate limits"
                }
            }
        )

    def _create_usage_limit_response(self, message: str) -> JSONResponse:
        """Create response for usage limit exceeded."""
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "usage_limit_exceeded",
                "message": message,
                "upgrade_url": "/payments/checkout",
                "details": {
                    "error_code": "USAGE_LIMIT_EXCEEDED",
                    "suggestion": "Upgrade your subscription for higher usage limits"
                }
            }
        )

    async def _track_request_usage(
        self,
        user_id: str,
        endpoint: str,
        method: str,
        subscription_tier: SubscriptionTier,
        request_duration_ms: int,
        response_status: int,
        billing_service: Optional[BillingService] = None
    ) -> None:
        """Track API usage for billing purposes."""
        if not billing_service:
            return

        try:
            # Estimate tokens used based on endpoint and response status
            tokens_used = self._estimate_tokens_used(endpoint, response_status)
            
            await billing_service.track_api_usage(
                user_id=int(user_id) if user_id.isdigit() else hash(user_id) % 1000000,
                endpoint=endpoint,
                tokens_used=tokens_used,
                method=method,
                request_duration_ms=request_duration_ms,
                subscription_tier=subscription_tier
            )
            
            log.debug(f"Tracked usage for user {user_id}: {endpoint} ({tokens_used} tokens)")
            
        except Exception as e:
            log.warning(f"Failed to track usage for user {user_id}: {e}")

    def _estimate_tokens_used(self, endpoint: str, response_status: int) -> int:
        """Estimate tokens used based on endpoint and response status."""
        # Simple estimation - in production this would be more sophisticated
        if response_status >= 400:
            return 10  # Error responses use minimal tokens
        
        endpoint_token_estimates = {
            "/ask": 500,
            "/ask/stream": 750,
            "/ask_philosophy": 800,
            "/ask_philosophy/stream": 1000,
            "/query_hybrid": 300,
            "/chat": 600,
        }
        
        for pattern, tokens in endpoint_token_estimates.items():
            if endpoint.startswith(pattern):
                return tokens
        
        return 100  # Default estimate


def create_subscription_middleware(
    subscription_manager: Optional[SubscriptionManager] = None,
    billing_service: Optional[BillingService] = None,
    auth_service: Optional[AuthService] = None,
    enabled: bool = True
) -> Callable:
    """
    Factory function to create subscription middleware.

    Args:
        subscription_manager: SubscriptionManager service instance
        billing_service: BillingService for usage tracking
        auth_service: AuthService for user context
        enabled: Whether subscription checking is enabled

    Returns:
        Middleware class configured with services
    """
    def middleware_factory(app):
        return SubscriptionMiddleware(
            app=app,
            subscription_manager=subscription_manager,
            billing_service=billing_service,
            auth_service=auth_service,
            enabled=enabled
        )
    
    return middleware_factory