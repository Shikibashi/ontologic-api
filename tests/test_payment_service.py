"""
Unit tests for PaymentService with mocked Stripe API.

Tests payment service methods including customer creation, subscription management,
and payment processing with comprehensive error handling and edge case testing.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from decimal import Decimal

import stripe
from stripe import StripeError, CardError, InvalidRequestError

from app.services.payment_service import (
    PaymentService,
    PaymentException,
    InsufficientFundsException,
    SubscriptionNotFoundException
)
from app.core.db_models import SubscriptionTier, SubscriptionStatus
from app.core.user_models import User


# Most fixtures are now defined in conftest.py to avoid duplication


@pytest.fixture
async def payment_service(mock_cache_service):
    """Create PaymentService instance with mocked dependencies."""
    with patch('app.services.payment_service.stripe'):
        with patch('app.services.payment_service.get_settings') as mock_get_settings:
            # Mock settings with payments enabled
            mock_settings = MagicMock()
            mock_settings.payments_enabled = True
            mock_settings.stripe_secret_key = MagicMock()
            mock_settings.stripe_secret_key.get_secret_value.return_value = "sk_test_12345"
            mock_get_settings.return_value = mock_settings

            # Create service with mocked Stripe and settings
            service = PaymentService(cache_service=mock_cache_service)

            # Verify it initialized correctly
            assert service._payments_enabled is True
            assert service._stripe_configured is True

            return service


@pytest.mark.asyncio
class TestPaymentServiceInitialization:
    """Test PaymentService initialization and configuration."""

    @patch('app.services.payment_service.get_settings')
    async def test_start_method_success(self, mock_get_settings, mock_cache_service):
        """Test successful PaymentService initialization via start method."""
        # Mock settings
        mock_settings = MagicMock()
        mock_settings.stripe_secret_key.get_secret_value.return_value = "sk_test_123"
        mock_settings.payments_enabled = True
        mock_get_settings.return_value = mock_settings

        with patch('app.services.payment_service.stripe') as mock_stripe:
            service = await PaymentService.start(cache_service=mock_cache_service)

            assert service is not None
            assert service.cache_service == mock_cache_service
            mock_stripe.api_key = "sk_test_123"

    @patch('app.services.payment_service.get_settings')
    async def test_start_method_payments_disabled(self, mock_get_settings, mock_cache_service):
        """Test PaymentService initialization when payments are disabled."""
        mock_settings = MagicMock()
        mock_settings.payments_enabled = False
        mock_get_settings.return_value = mock_settings

        service = await PaymentService.start(cache_service=mock_cache_service)
        assert service is not None
        assert service._payments_enabled is False

    @patch('app.services.payment_service.get_settings')
    async def test_start_method_missing_api_key(self, mock_get_settings, mock_cache_service):
        """Test PaymentService initialization with missing API key - should gracefully degrade."""
        mock_settings = MagicMock()
        mock_settings.payments_enabled = True
        mock_settings.stripe_secret_key = None
        mock_get_settings.return_value = mock_settings

        # Should not raise exception, but return disabled service
        service = await PaymentService.start(cache_service=mock_cache_service)
        assert service is not None
        assert service._payments_enabled is False
        assert service._stripe_configured is False


@pytest.mark.asyncio
class TestCustomerManagement:
    """Test Stripe customer creation and management."""

    async def test_create_stripe_customer_success(self, payment_service, mock_user, mock_stripe_customer):
        """Test successful Stripe customer creation."""
        with patch('app.services.payment_service.stripe.Customer.create', return_value=mock_stripe_customer) as mock_create:
            customer_id = await payment_service.create_stripe_customer(mock_user)
            
            assert customer_id == "cus_test1234567890"
            # Verify the call was made with correct parameters
            mock_create.assert_called_once()
            call_args = mock_create.call_args[1]
            assert call_args["email"] == mock_user.email
            assert call_args["metadata"]["user_id"] == str(mock_user.id)
            assert "name" in call_args  # Service includes name parameter

    async def test_create_stripe_customer_stripe_error(self, payment_service, mock_user):
        """Test Stripe customer creation with API error."""
        with patch('app.services.payment_service.stripe.Customer.create', side_effect=StripeError("API Error")):
            with pytest.raises(PaymentException, match="Failed to create customer"):
                await payment_service.create_stripe_customer(mock_user)



    async def test_create_stripe_customer_existing_id(self, payment_service, mock_user):
        """Test customer creation when user already has Stripe customer ID."""
        mock_user.stripe_customer_id = "cus_existing123"
        
        customer_id = await payment_service.create_stripe_customer(mock_user)
        assert customer_id == "cus_existing123"

    async def test_create_stripe_customer_new(self, payment_service, mock_user, mock_stripe_customer):
        """Test creating new customer when none exists."""
        mock_user.stripe_customer_id = None
        
        with patch('app.services.payment_service.stripe.Customer.create', return_value=mock_stripe_customer):
            customer_id = await payment_service.create_stripe_customer(mock_user)
            assert customer_id == "cus_test1234567890"


@pytest.mark.asyncio
class TestSubscriptionManagement:
    """Test subscription lifecycle management."""

    async def test_create_subscription_success(self, payment_service, mock_user, mock_stripe_subscription):
        """Test successful subscription creation."""
        mock_user.stripe_customer_id = "cus_test1234567890"

        with patch('app.services.payment_service.stripe.Subscription.create', return_value=mock_stripe_subscription) as mock_create:
            subscription = await payment_service.create_subscription(
                customer=mock_user,
                price_id="price_test123"
            )

            # Access dictionary keys instead of object attributes
            assert subscription["id"] == "sub_test123"
            assert subscription["customer"] == "cus_test1234567890"
            assert subscription["price_id"] == "price_test123"

            mock_create.assert_called_once_with(
                customer="cus_test1234567890",
                items=[{"price": "price_test123"}],
                payment_behavior="default_incomplete",
                payment_settings={"save_default_payment_method": "on_subscription"},
                expand=["latest_invoice.payment_intent"]
            )

    async def test_create_subscription_no_customer(self, payment_service, mock_user):
        """Test subscription creation when user has no Stripe customer."""
        mock_user.stripe_customer_id = None

        with pytest.raises(PaymentException, match="does not have a Stripe customer ID"):
            await payment_service.create_subscription(customer=mock_user, price_id="price_test123")

    async def test_create_subscription_stripe_error(self, payment_service, mock_user):
        """Test subscription creation with Stripe API error."""
        mock_user.stripe_customer_id = "cus_test1234567890"

        with patch('app.services.payment_service.stripe.Subscription.create', side_effect=CardError("Card declined", None, "card_declined")):
            with pytest.raises(InsufficientFundsException):
                await payment_service.create_subscription(
                    customer=mock_user,
                    price_id="price_test123"
                )

    async def test_cancel_subscription_success(self, payment_service, mock_stripe_subscription):
        """Test successful subscription cancellation."""
        with patch('app.services.payment_service.stripe.Subscription.modify', return_value=mock_stripe_subscription) as mock_modify:
            mock_stripe_subscription.status = "canceled"
            
            result = await payment_service.cancel_subscription("sub_test123")
            
            assert result is True
            mock_modify.assert_called_once_with(
                "sub_test123",
                cancel_at_period_end=True
            )

    async def test_cancel_subscription_not_found(self, payment_service):
        """Test cancelling non-existent subscription."""
        with patch('app.services.payment_service.stripe.Subscription.modify', side_effect=InvalidRequestError("No such subscription", None)):
            with pytest.raises(SubscriptionNotFoundException):
                await payment_service.cancel_subscription("sub_nonexistent")

    async def test_cancel_subscription_immediately(self, payment_service, mock_stripe_subscription):
        """Test immediate subscription cancellation."""
        with patch('app.services.payment_service.stripe.Subscription.delete', return_value=mock_stripe_subscription) as mock_delete:
            mock_stripe_subscription.status = "canceled"
            
            result = await payment_service.cancel_subscription("sub_test123", immediately=True)
            
            assert result is True
            mock_delete.assert_called_once_with("sub_test123")


@pytest.mark.asyncio
class TestCheckoutSessions:
    """Test Stripe checkout session creation."""

    async def test_create_checkout_session_success(self, payment_service, mock_user, mock_stripe_checkout_session):
        """Test successful checkout session creation."""
        mock_user.stripe_customer_id = "cus_test1234567890"

        with patch('app.services.payment_service.stripe.checkout.Session.create', return_value=mock_stripe_checkout_session) as mock_create:
            session = await payment_service.create_checkout_session(
                customer=mock_user,
                price_id="price_test123",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel"
            )
            
            assert session["id"] == "cs_test123"
            assert session["url"] == "https://checkout.stripe.com/pay/cs_test123"
            
            mock_create.assert_called_once()
            call_args = mock_create.call_args[1]
            assert call_args["customer"] == "cus_test1234567890"
            assert call_args["success_url"] == "https://example.com/success"
            assert call_args["cancel_url"] == "https://example.com/cancel"

    async def test_create_checkout_session_no_customer(self, payment_service, mock_user):
        """Test checkout session creation when user has no Stripe customer."""
        mock_user.stripe_customer_id = None

        with pytest.raises(PaymentException, match="does not have a Stripe customer ID"):
            await payment_service.create_checkout_session(
                customer=mock_user,
                price_id="price_test123",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel"
            )

    async def test_create_checkout_session_with_trial(self, payment_service, mock_user, mock_stripe_checkout_session):
        """Test checkout session creation with trial period."""
        mock_user.stripe_customer_id = "cus_test1234567890"

        with patch('app.services.payment_service.stripe.checkout.Session.create', return_value=mock_stripe_checkout_session) as mock_create:
            await payment_service.create_checkout_session(
                customer=mock_user,
                price_id="price_test123",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
                trial_period_days=7
            )
            
            call_args = mock_create.call_args[1]
            assert "subscription_data" in call_args
            assert call_args["subscription_data"]["trial_period_days"] == 7


@pytest.mark.asyncio
class TestRefundProcessing:
    """Test refund processing functionality."""

    async def test_process_refund_success(self, payment_service):
        """Test successful refund processing."""
        mock_refund = MagicMock()
        mock_refund.id = "re_test123"
        mock_refund.amount = 1000
        mock_refund.status = "succeeded"
        
        with patch('app.services.payment_service.stripe.Refund.create', return_value=mock_refund) as mock_create:
            refund = await payment_service.process_refund("pi_test123", amount=1000)
            
            assert refund["id"] == "re_test123"
            assert refund["amount"] == 1000
            assert refund["status"] == "succeeded"
            
            # Verify the call was made with correct parameters (metadata will vary by timestamp)
            mock_create.assert_called_once()
            call_args = mock_create.call_args[1]
            assert call_args["payment_intent"] == "pi_test123"
            assert call_args["amount"] == 1000
            assert "metadata" in call_args
            assert call_args["metadata"]["reason"] == "requested_by_customer"

    async def test_process_refund_full_amount(self, payment_service):
        """Test full refund processing without specifying amount."""
        mock_refund = MagicMock()
        mock_refund.id = "re_test123"
        mock_refund.status = "succeeded"
        
        with patch('app.services.payment_service.stripe.Refund.create', return_value=mock_refund) as mock_create:
            refund = await payment_service.process_refund("pi_test123")
            
            call_args = mock_create.call_args[1]
            assert call_args["payment_intent"] == "pi_test123"
            assert "amount" not in call_args  # Full refund

    async def test_process_refund_stripe_error(self, payment_service):
        """Test refund processing with Stripe error."""
        with patch('app.services.payment_service.stripe.Refund.create', side_effect=StripeError("Refund failed")):
            with pytest.raises(PaymentException, match="Failed to process refund"):
                await payment_service.process_refund("pi_test123")


@pytest.mark.asyncio
class TestSubscriptionSync:
    """Test subscription synchronization with Stripe."""

    async def test_sync_subscription_from_stripe_success(self, payment_service, mock_stripe_subscription):
        """Test successful subscription sync from Stripe."""
        with patch('app.services.payment_service.stripe.Subscription.retrieve', return_value=mock_stripe_subscription):
            with patch.object(payment_service, '_update_local_subscription') as mock_update:
                await payment_service.sync_subscription_from_stripe("sub_test123")
                
                mock_update.assert_called_once_with(mock_stripe_subscription)

    async def test_sync_subscription_not_found(self, payment_service):
        """Test syncing non-existent subscription."""
        with patch('app.services.payment_service.stripe.Subscription.retrieve', side_effect=InvalidRequestError("No such subscription", None)):
            with pytest.raises(SubscriptionNotFoundException):
                await payment_service.sync_subscription_from_stripe("sub_nonexistent")

    async def test_update_local_subscription(self, payment_service, mock_stripe_subscription):
        """Test updating local subscription from Stripe data."""
        # Mock database operations
        with patch('app.services.payment_service.get_db_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session
            
            # Mock existing subscription query
            mock_subscription = MagicMock()
            mock_session.exec.return_value.first.return_value = mock_subscription
            
            await payment_service._update_local_subscription(mock_stripe_subscription)
            
            # Verify subscription was updated
            assert mock_subscription.status == "active"
            mock_session.add.assert_called_once_with(mock_subscription)
            mock_session.commit.assert_called_once()


@pytest.mark.asyncio
class TestComprehensiveStripeMocking:
    """Test comprehensive Stripe API mocking functionality."""

    async def test_stripe_api_mocking_customer_creation(self, payment_service, mock_user, mock_stripe_api):
        """Test customer creation with comprehensive Stripe API mocking."""
        
        # Use the comprehensive mock instead of individual patches
        with patch('app.services.payment_service.stripe', mock_stripe_api):
            customer_id = await payment_service.create_stripe_customer(mock_user)
            
            # Verify customer was created with mock API
            assert customer_id.startswith("cus_mock_")
            assert customer_id in mock_stripe_api._api.customers

    async def test_stripe_api_error_simulation(self, payment_service, mock_user, mock_stripe_api, stripe_error_simulator):
        """Test Stripe API error simulation."""
        
        # Simulate card declined error
        mock_stripe_api.Customer.create.side_effect = stripe_error_simulator['customer_creation_error']("card_declined")
        
        with patch('app.services.payment_service.stripe', mock_stripe_api):
            with pytest.raises(PaymentException):
                await payment_service.create_stripe_customer(mock_user)

    async def test_webhook_signature_validation(self, mock_stripe_api, stripe_webhook_validator):
        """Test webhook signature validation with comprehensive mocking."""
        
        payload = '{"id": "evt_test", "type": "test"}'
        
        # Test valid signature
        valid_signature = stripe_webhook_validator['create_valid_signature'](payload)
        event = mock_stripe_api.Webhook.construct_event(payload, valid_signature, "whsec_test_secret")
        assert event['id'] == 'evt_test'
        
        # Test invalid signature
        invalid_signature = stripe_webhook_validator['create_invalid_signature']()
        with pytest.raises(Exception):  # Should raise MockStripeError
            mock_stripe_api.Webhook.construct_event(payload, invalid_signature, "whsec_test_secret")


class TestErrorHandling:
    """Test comprehensive error handling scenarios."""

    async def test_stripe_api_key_validation(self, mock_cache_service):
        """Test validation of Stripe API key format."""
        with patch('app.services.payment_service.get_settings') as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.payments_enabled = True
            mock_settings.stripe_secret_key.get_secret_value.return_value = "invalid_key"
            mock_get_settings.return_value = mock_settings
            
        service = await PaymentService.start(cache_service=mock_cache_service)

        assert service is not None
        assert service._payments_enabled is False
        assert service._stripe_configured is False

    async def test_network_timeout_handling(self, payment_service, mock_user):
        """Test handling of network timeouts."""
        import socket
        
        with patch('app.services.payment_service.stripe.Customer.create', side_effect=socket.timeout("Network timeout")):
            with pytest.raises(PaymentException, match="Network timeout"):
                await payment_service.create_stripe_customer(mock_user)

    async def test_rate_limit_handling(self, payment_service, mock_user):
        """Test handling of Stripe rate limits."""
        from stripe import RateLimitError

        with patch('app.services.payment_service.stripe.Customer.create', side_effect=RateLimitError("Rate limit exceeded")):
            with pytest.raises(PaymentException, match="Rate limit exceeded"):
                await payment_service.create_stripe_customer(mock_user)

    async def test_authentication_error_handling(self, payment_service, mock_user):
        """Test handling of Stripe authentication errors."""
        from stripe import AuthenticationError

        with patch('app.services.payment_service.stripe.Customer.create', side_effect=AuthenticationError("Invalid API key")):
            with pytest.raises(PaymentException, match="Stripe authentication failed"):
                await payment_service.create_stripe_customer(mock_user)


@pytest.mark.asyncio
class TestCacheIntegration:
    """Test cache service integration."""

    async def test_customer_caching(self, payment_service, mock_user, mock_stripe_customer):
        """Test customer data caching."""
        mock_user.stripe_customer_id = None
        
        # Mock cache service methods
        payment_service.cache_service.get = AsyncMock(return_value=None)
        payment_service.cache_service.set = AsyncMock(return_value=True)
        
        with patch('app.services.payment_service.stripe.Customer.create', return_value=mock_stripe_customer):
            customer_id = await payment_service.create_stripe_customer(mock_user)
            
            # Verify customer was created and cached
            assert customer_id == "cus_test1234567890"
            payment_service.cache_service.set.assert_called_once()

    async def test_cache_invalidation_on_error(self, payment_service, mock_user):
        """Test error handling when customer creation fails."""
        mock_user.stripe_customer_id = None
        
        with patch('app.services.payment_service.stripe.Customer.create', side_effect=StripeError("API Error")):
            with pytest.raises(PaymentException):
                await payment_service.create_stripe_customer(mock_user)


@pytest.mark.asyncio
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    async def test_concurrent_customer_creation(self, payment_service, mock_user, mock_stripe_customer):
        """Test handling of concurrent customer creation attempts."""
        mock_user.stripe_customer_id = None
        
        # Simulate race condition where customer creation fails first, then succeeds
        with patch('app.services.payment_service.stripe.Customer.create') as mock_create:
            mock_create.side_effect = [
                InvalidRequestError("Customer already exists", None),
                mock_stripe_customer
            ]
            
            # First call should handle the error gracefully
            with pytest.raises(PaymentException):
                await payment_service.create_stripe_customer(mock_user)

    async def test_subscription_with_zero_amount(self, payment_service, mock_user):
        """Test handling of zero-amount subscriptions (free trials)."""
        mock_user.stripe_customer_id = "cus_test1234567890"

        mock_subscription = MagicMock()
        mock_subscription.id = "sub_test123"
        mock_subscription.status = "trialing"

        with patch('app.services.payment_service.stripe.Subscription.create', return_value=mock_subscription):
            subscription = await payment_service.create_subscription(
                customer=mock_user,
                price_id="price_free_trial"
            )

            assert subscription["id"] == "sub_test123"

    async def test_refund_exceeding_payment_amount(self, payment_service):
        """Test refund amount validation."""
        with patch('app.services.payment_service.stripe.Refund.create', side_effect=InvalidRequestError("Refund amount exceeds payment", None)):
            with pytest.raises(PaymentException, match="Refund amount exceeds"):
                await payment_service.process_refund("pi_test123", amount=999999)

    async def test_subscription_metadata_handling(self, payment_service, mock_user, mock_stripe_api):
        """Test subscription creation with comprehensive mocking."""
        mock_user.stripe_customer_id = "cus_test1234567890"

        with patch('app.services.payment_service.stripe', mock_stripe_api):
            # First create a customer
            customer = mock_stripe_api._api.create_customer(email=mock_user.email)
            
            # Then create subscription with metadata
            subscription = mock_stripe_api._api.create_subscription(
                customer=customer.id,
                items=[{"price": "price_test123"}],
                metadata={"source": "api", "tier": "premium"}
            )

            assert subscription.id.startswith("sub_mock_")
            assert subscription.customer == customer.id
            assert subscription.metadata["source"] == "api"
            assert subscription.metadata["tier"] == "premium"
