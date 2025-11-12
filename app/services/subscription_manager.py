"""
Subscription management service for tier validation and access control.

Handles subscription tier management, usage limit checking, and access control
integration with existing cache service and rate limiting infrastructure.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from dataclasses import dataclass

from sqlmodel import select, func

from app.config.settings import get_settings
from app.core.logger import log
from app.core.db_models import Subscription, SubscriptionTier, SubscriptionStatus, UsageRecord
from app.core.user_models import User
from app.core.database import AsyncSessionLocal

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService


class UsageLimitExceededException(Exception):
    """Raised when user exceeds their subscription usage limits."""
    pass


class SubscriptionException(Exception):
    """Raised when subscription operations fail."""
    pass


@dataclass
class UsageLimits:
    """Usage limits for a subscription tier."""
    requests_per_month: int
    max_tokens_per_request: int
    features: List[str]
    requests_per_minute: int


@dataclass
class UsageStats:
    """Current usage statistics for a user."""
    requests_this_month: int
    tokens_used_this_month: int
    requests_this_minute: int
    last_request_time: Optional[datetime]


class SubscriptionManager:
    """
    Subscription tier management and access control service.

    Provides subscription tier validation, usage limit enforcement, and
    integration with existing cache service for performance optimization.

    LIFECYCLE: This service should be initialized during application startup
    and stored in app.state for request-time access via dependency injection.
    """

    def __init__(self, cache_service: Optional['RedisCacheService'] = None):
        """
        Initialize SubscriptionManager with optional cache service.

        Args:
            cache_service: Optional RedisCacheService for caching subscription data.
                          If None, operations will not be cached.
        """
        self.cache_service = cache_service
        self.settings = get_settings()
        
        # Load tier configurations from settings
        self._tier_limits = self._load_tier_limits()
        
        if cache_service is None:
            log.warning("SubscriptionManager initialized without cache_service - subscription data will not be cached")

    @classmethod
    async def start(cls, cache_service: Optional['RedisCacheService'] = None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            cache_service: Optional RedisCacheService instance

        Returns:
            Initialized SubscriptionManager instance
        """
        instance = cls(cache_service=cache_service)
        await instance._initialize()
        log.info("SubscriptionManager initialized for lifespan management")
        return instance

    async def _initialize(self):
        """
        Initialize the subscription manager with async operations.
        
        This method handles any async initialization that needs to be done
        after the service is created, such as database connections or
        cache service validations.
        """
        try:
            # Test database connectivity
            async with AsyncSessionLocal() as session:
                # Simple query to test database connection
                await session.execute(select(1))
                log.info("SubscriptionManager database connection verified")
            
            # Initialize cache service if available
            if self.cache_service:
                # Test cache connectivity
                test_key = self._make_cache_key("test", "connection")
                await self.cache_service.set(test_key, {"status": "ok"}, 60, cache_type='subscription')
                await self.cache_service.delete(test_key)
                log.info("SubscriptionManager cache connection verified")
            
            log.info("SubscriptionManager initialization completed successfully")
            
        except Exception as e:
            log.error(f"SubscriptionManager initialization failed: {e}")
            # Don't raise the exception to allow graceful degradation
            # The service will still work but may have reduced functionality

    def _load_tier_limits(self) -> Dict[SubscriptionTier, UsageLimits]:
        """Load subscription tier limits from settings."""
        return {
            SubscriptionTier.FREE: UsageLimits(
                requests_per_month=getattr(self.settings, 'free_tier_requests_per_month', 1000),
                max_tokens_per_request=2000,
                features=["basic_search"],
                requests_per_minute=10
            ),
            SubscriptionTier.BASIC: UsageLimits(
                requests_per_month=getattr(self.settings, 'basic_tier_requests_per_month', 10000),
                max_tokens_per_request=4000,
                features=["basic_search", "standard_search", "basic_support", "chat_history"],
                requests_per_minute=60
            ),
            SubscriptionTier.PREMIUM: UsageLimits(
                requests_per_month=getattr(self.settings, 'premium_tier_requests_per_month', 100000),
                max_tokens_per_request=8000,
                features=["basic_search", "standard_search", "advanced_search", "priority_support", "analytics", "bulk_export"],
                requests_per_minute=300
            ),
            SubscriptionTier.ACADEMIC: UsageLimits(
                requests_per_month=getattr(self.settings, 'academic_tier_requests_per_month', 50000),
                max_tokens_per_request=6000,
                features=["basic_search", "standard_search", "academic_discount", "research_tools", "bulk_export", "extended_context"],
                requests_per_minute=180
            ),
        }

    def _make_cache_key(self, prefix: str, *args) -> str:
        """Generate cache key for subscription data."""
        if not self.cache_service:
            return ""
        # Simple cache key generation
        key_parts = [f"subscription:{prefix}"] + [str(arg) for arg in args]
        return ":".join(key_parts)

    async def _get_cached_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get cached subscription data.

        Cache format: Stored as dict for JSON serialization.
        Keys: user_id, tier, status, current_period_start, current_period_end,
              stripe_customer_id, stripe_subscription_id

        Returns:
            Dict with subscription data or None if not cached
        """
        if not self.cache_service:
            return None

        cache_key = self._make_cache_key("user", user_id)
        return await self.cache_service.get(cache_key, cache_type='subscription')

    async def _cache_subscription(self, user_id: int, subscription_data: Dict[str, Any], ttl: int = 1800):
        """
        Cache subscription data (30 minutes default TTL).

        Cache format: Stored as dict for JSON serialization.
        Keys: user_id, tier, status, current_period_start, current_period_end,
              stripe_customer_id, stripe_subscription_id
        """
        if not self.cache_service:
            return

        cache_key = self._make_cache_key("user", user_id)
        await self.cache_service.set(cache_key, subscription_data, ttl, cache_type='subscription')

    def _normalize_usage_stats(self, cached_data: Any) -> Dict[str, Any]:
        """
        Normalize cached usage stats to a consistent dict format.

        The cache service always stores and returns dicts (via JSON serialization),
        but this helper handles any shape defensively for backwards compatibility.

        Args:
            cached_data: Cached data in any format (dict, UsageStats object, or object with attributes)

        Returns:
            Dict with keys: requests_this_month, tokens_used_this_month,
            requests_this_minute, last_request_time
        """
        if cached_data is None:
            return {
                'requests_this_month': 0,
                'tokens_used_this_month': 0,
                'requests_this_minute': 0,
                'last_request_time': None
            }

        # If already a UsageStats dataclass object
        if isinstance(cached_data, UsageStats):
            return {
                'requests_this_month': cached_data.requests_this_month,
                'tokens_used_this_month': cached_data.tokens_used_this_month,
                'requests_this_minute': cached_data.requests_this_minute,
                'last_request_time': cached_data.last_request_time
            }

        # If dict-like (has .get method) - expected format from cache
        if hasattr(cached_data, 'get'):
            return {
                'requests_this_month': cached_data.get('requests_this_month', 0),
                'tokens_used_this_month': cached_data.get('tokens_used_this_month', 0),
                'requests_this_minute': cached_data.get('requests_this_minute', 0),
                'last_request_time': cached_data.get('last_request_time')
            }

        # Fallback: object with attributes
        return {
            'requests_this_month': getattr(cached_data, 'requests_this_month', 0),
            'tokens_used_this_month': getattr(cached_data, 'tokens_used_this_month', 0),
            'requests_this_minute': getattr(cached_data, 'requests_this_minute', 0),
            'last_request_time': getattr(cached_data, 'last_request_time', None)
        }

    async def _get_cached_usage_stats(self, user_id: int) -> Optional[UsageStats]:
        """
        Get cached usage statistics.

        Cache format: Always stored and retrieved as dict with JSON serialization.
        Keys: requests_this_month, tokens_used_this_month, requests_this_minute, last_request_time

        Returns:
            UsageStats object or None if not cached
        """
        if not self.cache_service:
            return None

        cache_key = self._make_cache_key("usage", user_id)
        cached_data = await self.cache_service.get(cache_key, cache_type='usage')

        if cached_data:
            normalized = self._normalize_usage_stats(cached_data)
            return UsageStats(
                requests_this_month=normalized['requests_this_month'],
                tokens_used_this_month=normalized['tokens_used_this_month'],
                requests_this_minute=normalized['requests_this_minute'],
                last_request_time=normalized['last_request_time']
            )
        return None

    async def _cache_usage_stats(self, user_id: int, stats: UsageStats, ttl: int = 300):
        """
        Cache usage statistics (5 minutes default TTL).

        Cache format: Stored as dict for JSON serialization.
        Keys: requests_this_month, tokens_used_this_month, requests_this_minute, last_request_time
        """
        if not self.cache_service:
            return

        cache_key = self._make_cache_key("usage", user_id)
        cache_data = {
            'requests_this_month': stats.requests_this_month,
            'tokens_used_this_month': stats.tokens_used_this_month,
            'requests_this_minute': stats.requests_this_minute,
            'last_request_time': stats.last_request_time
        }
        await self.cache_service.set(cache_key, cache_data, ttl, cache_type='usage')

    async def get_user_subscription(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get user's subscription information.

        Args:
            user_id: User ID to get subscription for

        Returns:
            Dictionary containing subscription data or None if not found
        """
        # Try cache first
        cached_subscription = await self._get_cached_subscription(user_id)
        if cached_subscription:
            log.debug(f"Retrieved cached subscription for user {user_id}")
            return cached_subscription

        # Query from database
        async with AsyncSessionLocal() as session:
            stmt = select(Subscription).where(Subscription.user_id == user_id)
            result = await session.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                log.debug(f"No subscription found for user {user_id}")
                return None

            # Convert to dictionary for consistent interface
            subscription_data = {
                "user_id": subscription.user_id,
                "tier": subscription.tier,
                "status": subscription.status,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "stripe_customer_id": subscription.stripe_customer_id,
                "stripe_subscription_id": subscription.stripe_subscription_id,
            }

            # Cache the result
            await self._cache_subscription(user_id, subscription_data)

            log.debug(f"Retrieved subscription for user {user_id}")
            return subscription_data

    async def get_user_tier(self, user_id: int) -> SubscriptionTier:
        """
        Get user's subscription tier.

        Args:
            user_id: User ID to get tier for

        Returns:
            SubscriptionTier enum value (defaults to FREE if no subscription found)
        """
        subscription = await self.get_user_subscription(user_id)
        if subscription:
            # Subscription is always a dict from cache/database
            return subscription.get("tier", SubscriptionTier.FREE)
        return SubscriptionTier.FREE

    async def check_api_access(self, user_id: int, endpoint: str) -> bool:
        """
        Check if user has access to a specific API endpoint.

        Args:
            user_id: User ID to check access for
            endpoint: API endpoint to check access for

        Returns:
            True if user has access, False otherwise
        """
        # Get user's subscription tier and delegate the check to the helper
        tier = await self.get_user_tier(user_id)
        return self._is_endpoint_allowed(endpoint, tier)

    def _get_endpoint_features(self, endpoint: str) -> List[str]:
        """
        Map API endpoints to required features.

        Args:
            endpoint: API endpoint path

        Returns:
            List of required features for the endpoint
        """
        # Map endpoints to required features
        endpoint_feature_map = {
            "/ask": ["basic_search"],
            "/api/ask": ["basic_search"],
            "/query": ["basic_search"],
            "/api/query": ["basic_search"],
            "/chat": ["standard_search"],
            "/api/chat": ["standard_search"],
            "/upload": ["standard_search"],
            "/api/upload": ["standard_search"],
            "/analytics": ["analytics"],
            "/api/analytics": ["analytics"],
            "/premium-analytics": ["analytics"],
            "/api/premium-analytics": ["analytics"],
            "/bulk-export": ["bulk_export"],
            "/api/bulk-export": ["bulk_export"],
            "/research-tools": ["research_tools"],
            "/api/research-tools": ["research_tools"],
        }

        # Extract base endpoint from full path
        for base_endpoint, features in endpoint_feature_map.items():
            if endpoint.startswith(base_endpoint):
                return features

        # Default to basic search for unknown endpoints
        return ["basic_search"]

    def _is_endpoint_allowed(self, endpoint: str, tier: SubscriptionTier) -> bool:
        """
        Check if an endpoint is allowed for a given subscription tier.

        Args:
            endpoint: API endpoint path
            tier: Subscription tier to check

        Returns:
            True if endpoint is allowed for the tier
        """
        limits = self._tier_limits.get(tier)
        if not limits:
            return False

        required_features = self._get_endpoint_features(endpoint)
        
        # Check if all required features are available in the tier
        for feature in required_features:
            if feature not in limits.features:
                return False
        
        return True

    async def update_subscription_status(self, user_id: int, status: SubscriptionStatus) -> None:
        """
        Update user's subscription status.

        Args:
            user_id: User ID to update
            status: New subscription status
        """
        # Update in database
        async with AsyncSessionLocal() as session:
            stmt = select(Subscription).where(Subscription.user_id == user_id)
            result = await session.execute(stmt)
            subscription = result.scalar_one_or_none()

            if not subscription:
                log.warning(f"Cannot update status: No subscription found for user {user_id}")
                return

            subscription.status = status
            session.add(subscription)
            await session.commit()

        # Invalidate cache
        if self.cache_service:
            cache_key = self._make_cache_key("user", user_id)
            await self.cache_service.delete(cache_key)

        log.info(f"Updated subscription status for user {user_id} to {status}")

    async def get_usage_limits(self, tier: SubscriptionTier) -> UsageLimits:
        """
        Get usage limits for a subscription tier.

        Args:
            tier: Subscription tier to get limits for

        Returns:
            UsageLimits object with tier limits
        """
        return self._tier_limits.get(tier, self._tier_limits[SubscriptionTier.FREE])

    async def enforce_rate_limits(self, user_id: int, endpoint: str) -> bool:
        """
        Check and enforce rate limits for a user.

        Args:
            user_id: User ID to check limits for
            endpoint: API endpoint being accessed

        Returns:
            True if request is allowed, False if rate limited

        Raises:
            UsageLimitExceededException: If usage limits are exceeded
        """
        tier = await self.get_user_tier(user_id)
        limits = await self.get_usage_limits(tier)
        
        # Get current usage stats
        stats = await self._get_cached_usage_stats(user_id)
        if not stats:
            # Initialize stats for new user
            stats = UsageStats(
                requests_this_month=0,
                tokens_used_this_month=0,
                requests_this_minute=0,
                last_request_time=None
            )

        current_time = datetime.now(timezone.utc)
        
        # Check monthly limits
        if stats.requests_this_month >= limits.requests_per_month:
            log.warning(f"User {user_id} exceeded monthly request limit ({limits.requests_per_month})")
            raise UsageLimitExceededException(f"Monthly request limit of {limits.requests_per_month} exceeded")

        # Check per-minute rate limits
        if stats.last_request_time:
            time_diff = (current_time - stats.last_request_time).total_seconds()
            if time_diff < 60:  # Within the same minute
                if stats.requests_this_minute >= limits.requests_per_minute:
                    log.warning(f"User {user_id} exceeded per-minute rate limit ({limits.requests_per_minute})")
                    return False
            else:
                # Reset minute counter
                stats.requests_this_minute = 0

        # Update usage stats
        stats.requests_this_month += 1
        stats.requests_this_minute += 1
        stats.last_request_time = current_time

        # Cache updated stats
        await self._cache_usage_stats(user_id, stats)

        log.debug(f"Rate limit check passed for user {user_id} on {endpoint}")
        return True

    async def track_token_usage(self, user_id: int, tokens_used: int) -> None:
        """
        Track token usage for a user.

        Args:
            user_id: User ID to track usage for
            tokens_used: Number of tokens used in the request
        """
        # Get current usage stats
        stats = await self._get_cached_usage_stats(user_id)
        if not stats:
            stats = UsageStats(
                requests_this_month=0,
                tokens_used_this_month=0,
                requests_this_minute=0,
                last_request_time=None
            )

        # Update token usage
        stats.tokens_used_this_month += tokens_used

        # Cache updated stats
        await self._cache_usage_stats(user_id, stats)

        log.debug(f"Tracked {tokens_used} tokens for user {user_id}")

    async def check_token_limits(self, user_id: int, requested_tokens: int) -> bool:
        """
        Check if user can use the requested number of tokens.

        Args:
            user_id: User ID to check limits for
            requested_tokens: Number of tokens requested

        Returns:
            True if request is within limits, False otherwise
        """
        tier = await self.get_user_tier(user_id)
        limits = await self.get_usage_limits(tier)

        if requested_tokens > limits.max_tokens_per_request:
            log.warning(f"User {user_id} requested {requested_tokens} tokens, limit is {limits.max_tokens_per_request}")
            return False

        return True

    async def get_user_usage_stats(self, user_id: int) -> UsageStats:
        """
        Get current usage statistics for a user.

        Args:
            user_id: User ID to get stats for

        Returns:
            UsageStats object with current usage
        """
        stats = await self._get_cached_usage_stats(user_id)
        if not stats:
            # Return empty stats for new users
            stats = UsageStats(
                requests_this_month=0,
                tokens_used_this_month=0,
                requests_this_minute=0,
                last_request_time=None
            )

        return stats

    def get_tier_features(self, tier: SubscriptionTier) -> List[str]:
        """
        Get available features for a subscription tier.

        Args:
            tier: Subscription tier to get features for

        Returns:
            List of available features
        """
        limits = self._tier_limits.get(tier)
        return limits.features if limits else []

    async def is_feature_available(self, user_id: int, feature: str) -> bool:
        """
        Check if a feature is available for the user's subscription tier.

        Args:
            user_id: User ID to check feature for
            feature: Feature name to check

        Returns:
            True if feature is available, False otherwise
        """
        tier = await self.get_user_tier(user_id)
        available_features = self.get_tier_features(tier)
        return feature in available_features

    async def get_tier_features_async(self, tier: SubscriptionTier) -> List[str]:
        """
        Get available features for a subscription tier (async version).

        Args:
            tier: Subscription tier to get features for

        Returns:
            List of available features
        """
        return self.get_tier_features(tier)

    async def get_current_usage(self, user_id: int) -> UsageStats:
        """
        Get current month usage for a user from database.

        Args:
            user_id: User ID to get usage for

        Returns:
            UsageStats with current usage
        """
        # Check cache first
        cached_stats = await self._get_cached_usage_stats(user_id)
        if cached_stats:
            return cached_stats

        # Query from database
        current_date = datetime.now(timezone.utc)
        period_key = current_date.strftime("%Y-%m")

        async with AsyncSessionLocal() as session:
            stmt = select(UsageRecord).where(
                UsageRecord.user_id == user_id,
                UsageRecord.billing_period == period_key
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            requests_this_month = len(records)
            tokens_used = sum(r.tokens_used for r in records)

            # Get recent requests for rate limiting
            recent_time = current_date - timedelta(minutes=1)
            recent_records = [r for r in records if r.timestamp >= recent_time]

            stats = UsageStats(
                requests_this_month=requests_this_month,
                tokens_used_this_month=tokens_used,
                requests_this_minute=len(recent_records),
                last_request_time=max((r.timestamp for r in records), default=None) if records else None
            )

            # Cache the results
            await self._cache_usage_stats(user_id, stats)
            return stats

    async def check_usage_limits(self, user_id: int, tier: SubscriptionTier) -> bool:
        """
        Check if user is within usage limits.

        Args:
            user_id: User ID to check
            tier: Subscription tier

        Returns:
            True if within limits

        Raises:
            UsageLimitExceededException: If limits exceeded
        """
        limits = await self.get_usage_limits(tier)
        usage = await self.get_current_usage(user_id)

        if usage.requests_this_month >= limits.requests_per_month:
            raise UsageLimitExceededException(
                f"Monthly request limit exceeded: {limits.requests_per_month} requests"
            )

        if usage.requests_this_minute >= limits.requests_per_minute:
            raise UsageLimitExceededException(
                f"Rate limit exceeded: {limits.requests_per_minute} requests per minute"
            )

        return True

    async def track_api_usage(self, user_id: int, endpoint: str, tokens_used: int = 0) -> None:
        """
        Track API usage in database.

        Args:
            user_id: User ID
            endpoint: Endpoint accessed
            tokens_used: Tokens used in request
        """
        current_date = datetime.now(timezone.utc)
        period_key = current_date.strftime("%Y-%m")

        tier = await self.get_user_tier(user_id)

        async with AsyncSessionLocal() as session:
            usage_record = UsageRecord(
                user_id=user_id,
                endpoint=endpoint,
                tokens_used=tokens_used,
                billing_period=period_key,
                subscription_tier=tier,
                timestamp=current_date
            )
            session.add(usage_record)
            await session.commit()

        # Invalidate cache
        if self.cache_service:
            cache_key = self._make_cache_key("usage", user_id)
            await self.cache_service.delete(cache_key)

    def _is_in_grace_period(self, subscription: Dict[str, Any]) -> bool:
        """
        Check if subscription is in grace period.

        Args:
            subscription: Subscription data dict with keys: status, current_period_end

        Returns:
            True if in grace period (PAST_DUE status within 7 days after period end)
        """
        # Subscription is always a dict from cache/database
        status = subscription.get("status")
        period_end = subscription.get("current_period_end")

        if status != SubscriptionStatus.PAST_DUE:
            return False

        # Grace period is 7 days after period end
        if not period_end:
            return False

        grace_end = period_end + timedelta(days=7)
        return datetime.now(timezone.utc) < grace_end

    async def has_feature_access(self, user_id: int, feature: str) -> bool:
        """
        Check if user has access to a feature.

        Args:
            user_id: User ID
            feature: Feature name

        Returns:
            True if user has access
        """
        return await self.is_feature_available(user_id, feature)

    async def get_available_features(self, user_id: int) -> List[str]:
        """
        Get list of features available to user.

        Args:
            user_id: User ID

        Returns:
            List of feature names
        """
        tier = await self.get_user_tier(user_id)
        return self.get_tier_features(tier)

    async def apply_admin_override(
        self,
        user_id: int,
        new_tier: Optional[SubscriptionTier] = None,
        new_status: Optional[SubscriptionStatus] = None,
        extend_period_days: Optional[int] = None,
        admin_user_id: int = None,
        admin_notes: str = None
    ) -> Dict[str, Any]:
        """
        Apply administrative override to user subscription.

        Args:
            user_id: User ID to modify
            new_tier: New subscription tier (optional)
            new_status: New subscription status (optional)
            extend_period_days: Days to extend current period (optional)
            admin_user_id: Admin user performing override
            admin_notes: Administrative notes

        Returns:
            Dictionary with override results

        Raises:
            SubscriptionException: If override fails
        """
        from datetime import timedelta

        try:
            async with AsyncSessionLocal() as session:
                # Get current subscription
                stmt = select(Subscription).where(Subscription.user_id == user_id)
                result = await session.execute(stmt)
                subscription = result.scalar_one_or_none()

                if not subscription:
                    raise SubscriptionException(f"No subscription found for user {user_id}")

                old_tier = subscription.tier
                old_status = subscription.status
                period_extended = False

                # Apply tier change
                if new_tier and new_tier != subscription.tier:
                    subscription.tier = new_tier
                    log.info(f"Admin {admin_user_id} changed user {user_id} tier from {old_tier} to {new_tier}")

                # Apply status change
                if new_status and new_status != subscription.status:
                    subscription.status = new_status
                    log.info(f"Admin {admin_user_id} changed user {user_id} status from {old_status} to {new_status}")

                # Extend billing period
                if extend_period_days and extend_period_days > 0:
                    if subscription.current_period_end:
                        subscription.current_period_end += timedelta(days=extend_period_days)
                        period_extended = True
                        log.info(f"Admin {admin_user_id} extended user {user_id} period by {extend_period_days} days")

                session.add(subscription)
                await session.commit()
                await session.refresh(subscription)

                # Clear cache for this user
                if self.cache_service:
                    cache_key = self._make_cache_key("subscription", user_id)
                    await self.cache_service.delete(cache_key, cache_type='subscription')

                log.info(f"Admin override applied for user {user_id} by admin {admin_user_id}")

                return {
                    "new_tier": subscription.tier,
                    "new_status": subscription.status,
                    "period_extended": period_extended,
                    "admin_user_id": admin_user_id,
                    "admin_notes": admin_notes
                }

        except Exception as e:
            log.error(f"Failed to apply admin override for user {user_id}: {e}")
            raise SubscriptionException(f"Failed to apply admin override: {str(e)}")
