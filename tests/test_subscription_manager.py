"""
Unit tests for SubscriptionManager tier logic and access control.

Tests subscription tier validation, usage limit checking, and access control
with comprehensive error handling and edge case testing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.services.subscription_manager import (
    SubscriptionManager,
    UsageLimitExceededException,
    UsageLimits,
    UsageStats
)
from app.core.db_models import SubscriptionTier, SubscriptionStatus, Subscription, UsageRecord
from app.core.user_models import User


@pytest.fixture
def mock_cache_service():
    """Mock cache service for subscription manager testing."""
    cache = AsyncMock()
    cache.get.return_value = None
    cache.set.return_value = True
    cache.delete.return_value = True
    return cache


@pytest.fixture
def mock_user():
    """Mock user object for testing."""
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "test@example.com"
    user.subscription_tier = SubscriptionTier.BASIC
    user.subscription_status = SubscriptionStatus.ACTIVE
    user.stripe_customer_id = "cus_test1234567890"
    return user


@pytest.fixture
def mock_subscription():
    """Mock subscription object for testing."""
    subscription = MagicMock(spec=Subscription)
    subscription.id = 1
    subscription.user_id = 1
    subscription.tier = SubscriptionTier.BASIC
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_start = datetime.utcnow() - timedelta(days=15)
    subscription.current_period_end = datetime.utcnow() + timedelta(days=15)
    subscription.stripe_customer_id = "cus_test1234567890"
    subscription.stripe_subscription_id = "sub_test123"
    return subscription


@pytest.fixture
async def subscription_manager(mock_cache_service):
    """Create SubscriptionManager instance with mocked dependencies."""
    with patch('app.services.subscription_manager.get_settings') as mock_get_settings:
        mock_settings = MagicMock()
        mock_settings.free_tier_requests_per_month = 1000
        mock_settings.basic_tier_requests_per_month = 10000
        mock_settings.premium_tier_requests_per_month = 100000
        mock_settings.academic_tier_requests_per_month = 50000
        mock_get_settings.return_value = mock_settings

        manager = SubscriptionManager(cache_service=mock_cache_service)
        return manager


class TestSubscriptionManagerInitialization:
    """Test SubscriptionManager initialization and configuration."""

    @patch('app.services.subscription_manager.get_settings')
    async def test_start_method_success(self, mock_get_settings, mock_cache_service):
        """Test successful SubscriptionManager initialization via start method."""
        mock_settings = MagicMock()
        mock_settings.free_tier_requests_per_month = 1000
        mock_get_settings.return_value = mock_settings

        manager = await SubscriptionManager.start(cache_service=mock_cache_service)

        assert manager is not None
        assert manager.cache_service == mock_cache_service

    async def test_tier_limits_configuration(self, subscription_manager):
        """Test that tier limits are properly configured."""
        free_limits = await subscription_manager.get_usage_limits(SubscriptionTier.FREE)
        basic_limits = await subscription_manager.get_usage_limits(SubscriptionTier.BASIC)
        premium_limits = await subscription_manager.get_usage_limits(SubscriptionTier.PREMIUM)
        academic_limits = await subscription_manager.get_usage_limits(SubscriptionTier.ACADEMIC)
        
        assert free_limits.requests_per_month == 1000
        assert basic_limits.requests_per_month == 10000
        assert premium_limits.requests_per_month == 100000
        assert academic_limits.requests_per_month == 50000
        
        # Verify feature differences
        assert "basic_search" in free_limits.features
        assert "chat_history" in basic_limits.features
        assert "analytics" in premium_limits.features
        assert "research_tools" in academic_limits.features


class TestSubscriptionRetrieval:
    """Test subscription retrieval and caching."""

    async def test_get_user_subscription_success(self, subscription_manager, mock_subscription):
        """Test successful subscription retrieval."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_subscription
            mock_session.execute = AsyncMock(return_value=mock_result)

            subscription = await subscription_manager.get_user_subscription(1)

            assert subscription is not None
            assert subscription["user_id"] == 1

    async def test_get_user_subscription_not_found(self, subscription_manager):
        """Test subscription retrieval when subscription doesn't exist."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)

            subscription = await subscription_manager.get_user_subscription(1)

            assert subscription is None

    async def test_get_user_subscription_cached(self, subscription_manager, mock_subscription):
        """Test subscription retrieval from cache."""
        cache_key = "subscription:1"
        subscription_manager.cache_service.get.return_value = mock_subscription
        
        subscription = await subscription_manager.get_user_subscription(1)
        
        assert subscription == mock_subscription
        subscription_manager.cache_service.get.assert_called_once_with(cache_key)

    async def test_get_user_tier_from_subscription(self, subscription_manager, mock_subscription):
        """Test getting user tier from subscription."""
        with patch.object(subscription_manager, 'get_user_subscription', return_value=mock_subscription):
            tier = await subscription_manager.get_user_tier(1)
            
            assert tier == SubscriptionTier.BASIC

    async def test_get_user_tier_no_subscription(self, subscription_manager):
        """Test getting user tier when no subscription exists (defaults to FREE)."""
        with patch.object(subscription_manager, 'get_user_subscription', return_value=None):
            tier = await subscription_manager.get_user_tier(1)
            
            assert tier == SubscriptionTier.FREE


class TestAccessControl:
    """Test API access control based on subscription tier."""

    async def test_check_api_access_allowed(self, subscription_manager, mock_subscription):
        """Test API access check for allowed endpoint."""
        with patch.object(subscription_manager, 'get_user_subscription', return_value=mock_subscription):
            with patch.object(subscription_manager, '_is_endpoint_allowed', return_value=True):
                access = await subscription_manager.check_api_access(1, "/api/ask")
                
                assert access is True

    async def test_check_api_access_denied(self, subscription_manager, mock_subscription):
        """Test API access check for denied endpoint."""
        with patch.object(subscription_manager, 'get_user_subscription', return_value=mock_subscription):
            with patch.object(subscription_manager, '_is_endpoint_allowed', return_value=False):
                access = await subscription_manager.check_api_access(1, "/api/premium-feature")
                
                assert access is False

    async def test_check_api_access_inactive_subscription(self, subscription_manager, mock_subscription):
        """Test API access check with inactive subscription."""
        mock_subscription.status = SubscriptionStatus.CANCELED
        
        with patch.object(subscription_manager, 'get_user_subscription', return_value=mock_subscription):
            access = await subscription_manager.check_api_access(1, "/api/ask")
            
            assert access is False

    async def test_check_api_access_expired_subscription(self, subscription_manager, mock_subscription):
        """Test API access check with expired subscription."""
        mock_subscription.current_period_end = datetime.utcnow() - timedelta(days=1)
        
        with patch.object(subscription_manager, 'get_user_subscription', return_value=mock_subscription):
            access = await subscription_manager.check_api_access(1, "/api/ask")
            
            assert access is False

    async def test_is_endpoint_allowed_by_tier(self, subscription_manager):
        """Test endpoint access validation by tier."""
        # Free tier - basic endpoints only
        assert subscription_manager._is_endpoint_allowed("/api/ask", SubscriptionTier.FREE) is True
        assert subscription_manager._is_endpoint_allowed("/api/premium-analytics", SubscriptionTier.FREE) is False
        
        # Premium tier - all endpoints
        assert subscription_manager._is_endpoint_allowed("/api/ask", SubscriptionTier.PREMIUM) is True
        assert subscription_manager._is_endpoint_allowed("/api/premium-analytics", SubscriptionTier.PREMIUM) is True
        
        # Academic tier - research endpoints
        assert subscription_manager._is_endpoint_allowed("/api/research-tools", SubscriptionTier.ACADEMIC) is True
        assert subscription_manager._is_endpoint_allowed("/api/premium-analytics", SubscriptionTier.ACADEMIC) is False


class TestUsageLimits:
    """Test usage limit checking and enforcement."""

    async def test_get_usage_limits_all_tiers(self, subscription_manager):
        """Test usage limits for all subscription tiers."""
        tiers_and_limits = [
            (SubscriptionTier.FREE, 1000, 2000, 10),
            (SubscriptionTier.BASIC, 10000, 4000, 60),
            (SubscriptionTier.PREMIUM, 100000, 8000, 300),
            (SubscriptionTier.ACADEMIC, 50000, 6000, 180)
        ]
        
        for tier, expected_monthly, expected_tokens, expected_per_minute in tiers_and_limits:
            limits = await subscription_manager.get_usage_limits(tier)
            
            assert limits.requests_per_month == expected_monthly
            assert limits.max_tokens_per_request == expected_tokens
            assert limits.requests_per_minute == expected_per_minute

    async def test_check_usage_limits_within_limits(self, subscription_manager):
        """Test usage limit check when within limits."""
        usage_stats = UsageStats(
            requests_this_month=500,
            tokens_used_this_month=50000,
            requests_this_minute=5,
            last_request_time=datetime.utcnow() - timedelta(seconds=30)
        )
        
        with patch.object(subscription_manager, 'get_current_usage', return_value=usage_stats):
            result = await subscription_manager.check_usage_limits(1, SubscriptionTier.BASIC)
            
            assert result is True

    async def test_check_usage_limits_monthly_exceeded(self, subscription_manager):
        """Test usage limit check when monthly limit is exceeded."""
        usage_stats = UsageStats(
            requests_this_month=15000,  # Exceeds basic tier limit of 10000
            tokens_used_this_month=150000,
            requests_this_minute=5,
            last_request_time=datetime.utcnow() - timedelta(seconds=30)
        )
        
        with patch.object(subscription_manager, 'get_current_usage', return_value=usage_stats):
            with pytest.raises(UsageLimitExceededException, match="Monthly request limit exceeded"):
                await subscription_manager.check_usage_limits(1, SubscriptionTier.BASIC)

    async def test_check_usage_limits_rate_exceeded(self, subscription_manager):
        """Test usage limit check when rate limit is exceeded."""
        usage_stats = UsageStats(
            requests_this_month=500,
            tokens_used_this_month=50000,
            requests_this_minute=65,  # Exceeds basic tier limit of 60
            last_request_time=datetime.utcnow() - timedelta(seconds=5)
        )
        
        with patch.object(subscription_manager, 'get_current_usage', return_value=usage_stats):
            with pytest.raises(UsageLimitExceededException, match="Rate limit exceeded"):
                await subscription_manager.check_usage_limits(1, SubscriptionTier.BASIC)

    async def test_enforce_rate_limits_success(self, subscription_manager):
        """Test successful rate limit enforcement."""
        with patch.object(subscription_manager, 'check_usage_limits', return_value=True):
            result = await subscription_manager.enforce_rate_limits(1, "/api/ask")
            
            assert result is True

    async def test_enforce_rate_limits_exceeded(self, subscription_manager):
        """Test rate limit enforcement when limits are exceeded."""
        with patch.object(subscription_manager, 'check_usage_limits', side_effect=UsageLimitExceededException("Rate limit exceeded")):
            result = await subscription_manager.enforce_rate_limits(1, "/api/ask")
            
            assert result is False


class TestUsageTracking:
    """Test usage tracking and statistics."""

    async def test_get_current_usage_success(self, subscription_manager):
        """Test successful usage statistics retrieval."""
        mock_usage_records = [
            MagicMock(timestamp=datetime.utcnow() - timedelta(days=5), tokens_used=100),
            MagicMock(timestamp=datetime.utcnow() - timedelta(days=10), tokens_used=200),
            MagicMock(timestamp=datetime.utcnow() - timedelta(minutes=5), tokens_used=50)
        ]
        
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.return_value.all.return_value = mock_usage_records
            
            usage = await subscription_manager.get_current_usage(1)
            
            assert usage.requests_this_month == 3
            assert usage.tokens_used_this_month == 350

    async def test_get_current_usage_cached(self, subscription_manager):
        """Test usage statistics retrieval from cache."""
        cached_usage = UsageStats(
            requests_this_month=100,
            tokens_used_this_month=10000,
            requests_this_minute=5,
            last_request_time=datetime.utcnow()
        )
        
        subscription_manager.cache_service.get.return_value = cached_usage
        
        usage = await subscription_manager.get_current_usage(1)
        
        assert usage == cached_usage

    async def test_track_api_usage(self, subscription_manager):
        """Test API usage tracking."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            
            await subscription_manager.track_api_usage(1, "/api/ask", 150)
            
            # Verify usage record was created
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    async def test_track_api_usage_cache_invalidation(self, subscription_manager):
        """Test cache invalidation after usage tracking."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            
            await subscription_manager.track_api_usage(1, "/api/ask", 150)
            
            # Verify cache was invalidated
            subscription_manager.cache_service.delete.assert_called_with("usage:1")


class TestSubscriptionStatusUpdates:
    """Test subscription status update functionality."""

    async def test_update_subscription_status_success(self, subscription_manager, mock_subscription):
        """Test successful subscription status update."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.return_value.first.return_value = mock_subscription
            
            await subscription_manager.update_subscription_status(1, SubscriptionStatus.CANCELED)
            
            assert mock_subscription.status == SubscriptionStatus.CANCELED
            mock_session.add.assert_called_once_with(mock_subscription)
            mock_session.commit.assert_called_once()

    async def test_update_subscription_status_not_found(self, subscription_manager):
        """Test subscription status update when subscription doesn't exist."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.return_value.first.return_value = None
            
            # Should not raise exception, just log warning
            await subscription_manager.update_subscription_status(1, SubscriptionStatus.CANCELED)
            
            mock_session.add.assert_not_called()
            mock_session.commit.assert_not_called()

    async def test_update_subscription_status_cache_invalidation(self, subscription_manager, mock_subscription):
        """Test cache invalidation after status update."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.return_value.first.return_value = mock_subscription
            
            await subscription_manager.update_subscription_status(1, SubscriptionStatus.CANCELED)
            
            # Verify cache was invalidated
            subscription_manager.cache_service.delete.assert_called_with("subscription:1")


class TestGracePeriodHandling:
    """Test grace period handling for expired subscriptions."""

    async def test_is_in_grace_period_true(self, subscription_manager, mock_subscription):
        """Test grace period check when subscription is in grace period."""
        # Subscription expired 2 days ago, within 3-day grace period
        mock_subscription.current_period_end = datetime.utcnow() - timedelta(days=2)
        
        result = subscription_manager._is_in_grace_period(mock_subscription)
        
        assert result is True

    async def test_is_in_grace_period_false(self, subscription_manager, mock_subscription):
        """Test grace period check when subscription is beyond grace period."""
        # Subscription expired 5 days ago, beyond 3-day grace period
        mock_subscription.current_period_end = datetime.utcnow() - timedelta(days=5)
        
        result = subscription_manager._is_in_grace_period(mock_subscription)
        
        assert result is False

    async def test_is_in_grace_period_active(self, subscription_manager, mock_subscription):
        """Test grace period check for active subscription."""
        # Subscription expires in the future
        mock_subscription.current_period_end = datetime.utcnow() + timedelta(days=15)
        
        result = subscription_manager._is_in_grace_period(mock_subscription)
        
        assert result is False  # Not in grace period because still active

    async def test_check_api_access_grace_period(self, subscription_manager, mock_subscription):
        """Test API access during grace period."""
        mock_subscription.status = SubscriptionStatus.PAST_DUE
        mock_subscription.current_period_end = datetime.utcnow() - timedelta(days=1)
        
        with patch.object(subscription_manager, 'get_user_subscription', return_value=mock_subscription):
            with patch.object(subscription_manager, '_is_endpoint_allowed', return_value=True):
                access = await subscription_manager.check_api_access(1, "/api/ask")
                
                assert access is True  # Should allow access during grace period


class TestFeatureAccess:
    """Test feature access control based on subscription tier."""

    async def test_has_feature_access_true(self, subscription_manager):
        """Test feature access check for allowed feature."""
        limits = UsageLimits(
            requests_per_month=10000,
            max_tokens_per_request=4000,
            features=["chat_history", "basic_support"],
            requests_per_minute=60
        )
        
        with patch.object(subscription_manager, 'get_usage_limits', return_value=limits):
            access = await subscription_manager.has_feature_access(1, "chat_history")
            
            assert access is True

    async def test_has_feature_access_false(self, subscription_manager):
        """Test feature access check for denied feature."""
        limits = UsageLimits(
            requests_per_month=1000,
            max_tokens_per_request=2000,
            features=["basic_search"],
            requests_per_minute=10
        )
        
        with patch.object(subscription_manager, 'get_usage_limits', return_value=limits):
            access = await subscription_manager.has_feature_access(1, "analytics")
            
            assert access is False

    async def test_get_available_features(self, subscription_manager):
        """Test getting list of available features for user."""
        limits = UsageLimits(
            requests_per_month=10000,
            max_tokens_per_request=4000,
            features=["standard_search", "basic_support", "chat_history"],
            requests_per_minute=60
        )
        
        with patch.object(subscription_manager, 'get_usage_limits', return_value=limits):
            features = await subscription_manager.get_available_features(1)
            
            assert "standard_search" in features
            assert "basic_support" in features
            assert "chat_history" in features
            assert len(features) == 3


class TestErrorHandling:
    """Test error handling scenarios."""

    async def test_database_error_handling(self, subscription_manager):
        """Test handling of database errors."""
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.side_effect = Exception("Database error")
            
            subscription = await subscription_manager.get_user_subscription(1)
            
            assert subscription is None  # Should return None on error

    async def test_cache_error_handling(self, subscription_manager):
        """Test handling of cache errors."""
        subscription_manager.cache_service.get.side_effect = Exception("Cache error")
        
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.return_value.first.return_value = None
            
            # Should fall back to database query
            subscription = await subscription_manager.get_user_subscription(1)
            
            assert subscription is None

    async def test_invalid_tier_handling(self, subscription_manager):
        """Test handling of invalid subscription tier."""
        with pytest.raises(ValueError, match="Invalid subscription tier"):
            await subscription_manager.get_usage_limits("invalid_tier")


class TestConcurrencyAndRaceConditions:
    """Test concurrent access and race condition handling."""

    async def test_concurrent_usage_tracking(self, subscription_manager):
        """Test concurrent usage tracking doesn't cause data corruption."""
        import asyncio
        
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            
            # Simulate concurrent usage tracking
            tasks = [
                subscription_manager.track_api_usage(1, "/api/ask", 100)
                for _ in range(10)
            ]
            
            await asyncio.gather(*tasks)
            
            # Verify all usage records were created
            assert mock_session.add.call_count == 10
            assert mock_session.commit.call_count == 10

    async def test_cache_race_condition(self, subscription_manager, mock_subscription):
        """Test handling of cache race conditions."""
        # Simulate cache miss followed by concurrent cache set
        subscription_manager.cache_service.get.side_effect = [None, mock_subscription]
        
        with patch('app.services.subscription_manager.AsyncSessionLocal') as mock_session_maker:
            mock_session = AsyncMock()
            mock_session_maker.return_value.__aenter__.return_value = mock_session
            mock_session.exec.return_value.first.return_value = mock_subscription
            
            subscription = await subscription_manager.get_user_subscription(1)

            assert subscription == mock_subscription


class TestSubscriptionHelperMetrics:
    """Test metrics tracking for subscription helper degradation."""

    @pytest.mark.asyncio
    async def test_check_subscription_access_increments_failure_counter(self):
        """Test that subscription check failures increment the failure counter in fail-closed mode."""
        from app.core.subscription_helpers import check_subscription_access
        from fastapi import Request, HTTPException

        # Mock user
        user = MagicMock(spec=User)
        user.id = 1

        # Mock subscription manager that raises an exception
        subscription_manager = AsyncMock()
        subscription_manager.check_api_access = AsyncMock(side_effect=Exception("Database error"))

        # Mock request
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.request_id = "test-request-id"

        # Mock chat_monitoring
        with patch('app.core.subscription_helpers.chat_monitoring') as mock_monitoring, \
             patch('app.core.subscription_helpers.get_settings') as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.payments_enabled = True
            mock_settings_instance.subscription_fail_open = False  # Fail-closed mode
            mock_settings.return_value = mock_settings_instance

            # Should raise HTTPException 503 in fail-closed mode
            with pytest.raises(HTTPException) as exc_info:
                await check_subscription_access(user, subscription_manager, "/test", request)

            # Verify exception details
            assert exc_info.value.status_code == 503
            detail = exc_info.value.detail
            assert detail['error'] == 'access_denied'
            assert detail['details'][0]['type'] == 'authorization_error'
            assert "Subscription service temporarily unavailable" in detail['message']

            # Verify counter was incremented
            mock_monitoring.record_counter.assert_called_once_with(
                "subscription_check_failures",
                {"endpoint": "/test", "error_type": "Exception"}
            )

    @pytest.mark.asyncio
    async def test_check_subscription_access_fail_open_mode(self):
        """Test that subscription check failures are gracefully degraded in fail-open mode."""
        from app.core.subscription_helpers import check_subscription_access
        from fastapi import Request

        # Mock user
        user = MagicMock(spec=User)
        user.id = 1

        # Mock subscription manager that raises an exception
        subscription_manager = AsyncMock()
        subscription_manager.check_api_access = AsyncMock(side_effect=Exception("Database error"))

        # Mock request
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        request.state.request_id = "test-request-id"

        # Mock chat_monitoring
        with patch('app.core.subscription_helpers.chat_monitoring') as mock_monitoring, \
             patch('app.core.subscription_helpers.get_settings') as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.payments_enabled = True
            mock_settings_instance.subscription_fail_open = True  # Fail-open mode
            mock_settings.return_value = mock_settings_instance

            # Should not raise (graceful degradation)
            await check_subscription_access(user, subscription_manager, "/test", request)

            # Verify counter was incremented
            mock_monitoring.record_counter.assert_called_once_with(
                "subscription_check_failures",
                {"endpoint": "/test", "error_type": "Exception"}
            )

    @pytest.mark.asyncio
    async def test_track_subscription_usage_increments_failure_counter(self):
        """Test that subscription usage tracking failures increment the failure counter."""
        from app.core.subscription_helpers import track_subscription_usage

        # Mock user
        user = MagicMock(spec=User)
        user.id = 1

        # Mock subscription manager that raises an exception
        subscription_manager = AsyncMock()
        subscription_manager.track_api_usage = AsyncMock(side_effect=Exception("Database error"))

        # Mock chat_monitoring
        with patch('app.core.subscription_helpers.chat_monitoring') as mock_monitoring, \
             patch('app.core.subscription_helpers.get_settings') as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.payments_enabled = True
            mock_settings.return_value = mock_settings_instance

            # Should not raise (graceful degradation)
            await track_subscription_usage(user, subscription_manager, "/test", "response text")

            # Verify counter was incremented
            mock_monitoring.record_counter.assert_called_once_with(
                "subscription_tracking_failures",
                {"endpoint": "/test", "error_type": "Exception"}
            )

    @pytest.mark.asyncio
    async def test_track_subscription_usage_short_response_minimum_token(self):
        """Test that very short responses estimate to at least 1 token."""
        from app.core.subscription_helpers import track_subscription_usage

        # Mock user
        user = MagicMock(spec=User)
        user.id = 1

        # Mock subscription manager
        subscription_manager = AsyncMock()
        subscription_manager.track_api_usage = AsyncMock()

        # Mock settings
        with patch('app.core.subscription_helpers.get_settings') as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.payments_enabled = True
            mock_settings.return_value = mock_settings_instance

            # Very short response (2 characters)
            await track_subscription_usage(user, subscription_manager, "/test", "Hi")

            # Verify at least 1 token was counted
            subscription_manager.track_api_usage.assert_called_once()
            call_args = subscription_manager.track_api_usage.call_args
            assert call_args.kwargs["tokens_used"] == 1

    @pytest.mark.asyncio
    async def test_track_subscription_usage_empty_response_zero_tokens(self):
        """Test that empty responses estimate to 0 tokens."""
        from app.core.subscription_helpers import track_subscription_usage

        # Mock user
        user = MagicMock(spec=User)
        user.id = 1

        # Mock subscription manager
        subscription_manager = AsyncMock()
        subscription_manager.track_api_usage = AsyncMock()

        # Mock settings
        with patch('app.core.subscription_helpers.get_settings') as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.payments_enabled = True
            mock_settings.return_value = mock_settings_instance

            # Empty response
            await track_subscription_usage(user, subscription_manager, "/test", "")

            # Verify 0 tokens were counted
            subscription_manager.track_api_usage.assert_called_once()
            call_args = subscription_manager.track_api_usage.call_args
            assert call_args.kwargs["tokens_used"] == 0

    @pytest.mark.asyncio
    async def test_track_subscription_usage_ceiling_division(self):
        """Test that token estimation uses ceiling division."""
        from app.core.subscription_helpers import track_subscription_usage
        from app.core.constants import CHARS_PER_TOKEN_ESTIMATE

        # Mock user
        user = MagicMock(spec=User)
        user.id = 1

        # Mock subscription manager
        subscription_manager = AsyncMock()
        subscription_manager.track_api_usage = AsyncMock()

        # Mock settings
        with patch('app.core.subscription_helpers.get_settings') as mock_settings:
            mock_settings_instance = MagicMock()
            mock_settings_instance.payments_enabled = True
            mock_settings.return_value = mock_settings_instance

            # Response that would round down with integer division
            # With CHARS_PER_TOKEN_ESTIMATE=4, 5 chars should give 2 tokens (ceiling), not 1
            response_text = "12345"  # 5 characters
            await track_subscription_usage(user, subscription_manager, "/test", response_text)

            # Verify ceiling division was used
            subscription_manager.track_api_usage.assert_called_once()
            call_args = subscription_manager.track_api_usage.call_args
            expected_tokens = 2  # ceil(5 / 4) = 2
            assert call_args.kwargs["tokens_used"] == expected_tokens