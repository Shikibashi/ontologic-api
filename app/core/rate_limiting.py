"""Rate limiting configuration for the application."""
import os
from typing import Optional, Dict, Any
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.db_models import SubscriptionTier


def get_user_subscription_tier(request: Request) -> SubscriptionTier:
    """
    Get user's subscription tier for dynamic rate limiting.
    
    This function integrates with the subscription middleware to determine
    the user's subscription tier for dynamic rate limit calculation.
    """
    # Try to get subscription tier from request state (set by middleware)
    tier = getattr(request.state, "subscription_tier", None)
    if tier:
        return tier
    
    # Try to get from subscription manager if available
    subscription_manager = getattr(request.app.state, "subscription_manager", None)
    if subscription_manager:
        # This would require async context, so we'll use a default for now
        # In practice, the middleware should set this in request.state
        pass
    
    # Default to free tier
    return SubscriptionTier.FREE


def get_dynamic_rate_limit_key(request: Request) -> str:
    """
    Generate rate limit key based on user subscription tier.
    
    This allows different rate limits for different subscription tiers
    while maintaining backward compatibility with existing rate limiting.
    """
    # Get base key (IP address)
    base_key = get_remote_address(request)
    
    # Get subscription tier
    tier = get_user_subscription_tier(request)
    
    # Append tier to key for tier-specific rate limiting
    return f"{base_key}:{tier.value}"


def get_tier_rate_limit(tier: SubscriptionTier, endpoint_type: str = "default") -> str:
    """
    Get rate limit string for a subscription tier and endpoint type.
    
    Args:
        tier: User's subscription tier
        endpoint_type: Type of endpoint (default, streaming, heavy, etc.)
    
    Returns:
        Rate limit string in SlowAPI format (e.g., "60/minute")
    """
    # Rate limits per tier per minute
    tier_limits = {
        SubscriptionTier.FREE: {
            "default": "10/minute",
            "streaming": "5/minute", 
            "heavy": "2/minute",
            "upload": "3/minute"
        },
        SubscriptionTier.BASIC: {
            "default": "60/minute",
            "streaming": "20/minute",
            "heavy": "10/minute", 
            "upload": "15/minute"
        },
        SubscriptionTier.PREMIUM: {
            "default": "300/minute",
            "streaming": "100/minute",
            "heavy": "50/minute",
            "upload": "75/minute"
        },
        SubscriptionTier.ACADEMIC: {
            "default": "180/minute",
            "streaming": "60/minute", 
            "heavy": "30/minute",
            "upload": "45/minute"
        }
    }
    
    return tier_limits.get(tier, tier_limits[SubscriptionTier.FREE]).get(
        endpoint_type, tier_limits[tier]["default"]
    )


def create_limiter():
    """
    Create a limiter instance with Redis storage for production or in-memory for development.
    
    Uses Redis for shared rate limiting across multiple workers in production,
    falls back to in-memory storage for local development.
    
    Enhanced with subscription-aware rate limiting.
    """
    # Get Redis URL from environment or config
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    app_env = os.environ.get("APP_ENV", "dev").lower()
    
    # Use Redis storage for production environments
    if app_env in ("prod", "production"):
        try:
            from slowapi.middleware import SlowAPIMiddleware
            from slowapi._limiter import Limiter as SlowAPILimiter
            import redis.asyncio as redis
            
            # Create Redis connection for rate limiting
            redis_client = redis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            
            # Create limiter with Redis storage and dynamic key function
            limiter = Limiter(
                key_func=get_dynamic_rate_limit_key,
                storage_uri=redis_url
            )
            
            print(f"Rate limiting configured with Redis backend and subscription tiers: {redis_url}")
            return limiter
            
        except ImportError as e:
            print(f"Warning: Redis dependencies not available ({e}), falling back to in-memory rate limiting")
        except Exception as e:
            print(f"Warning: Failed to connect to Redis ({e}), falling back to in-memory rate limiting")
    
    # Fallback to in-memory storage for development or if Redis fails
    limiter = Limiter(key_func=get_dynamic_rate_limit_key)
    print(f"Rate limiting configured with in-memory backend and subscription tiers (env: {app_env})")
    return limiter


def create_subscription_aware_limit(endpoint_type: str = "default"):
    """
    Create a rate limit decorator that adapts to user subscription tier.
    
    Args:
        endpoint_type: Type of endpoint for tier-specific limits
    
    Returns:
        Function that returns appropriate rate limit for user's tier
    """
    def get_limit_for_request(request: Request) -> str:
        tier = get_user_subscription_tier(request)
        return get_tier_rate_limit(tier, endpoint_type)
    
    return get_limit_for_request


# Create a shared limiter instance that can be imported by routers
limiter = create_limiter()


# Convenience functions for common endpoint types
# These return the limit function that slowapi can call with the request
def get_default_limit():
    """Get default rate limit function for user's subscription tier."""
    return create_subscription_aware_limit("default")


def get_streaming_limit():
    """Get streaming rate limit function for user's subscription tier."""
    return create_subscription_aware_limit("streaming")


def get_heavy_limit():
    """Get heavy operation rate limit function for user's subscription tier."""
    return create_subscription_aware_limit("heavy")


def get_upload_limit():
    """Get upload rate limit function for user's subscription tier."""
    return create_subscription_aware_limit("upload")