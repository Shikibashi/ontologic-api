#!/usr/bin/env python3
"""
Payment System Integration Tests

Tests the payment processing functionality including:
- Payment service initialization
- Subscription management
- Billing operations
- API endpoint availability
"""

import sys
from pathlib import Path
import pytest

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import get_settings
from app.core.logger import log

# Check Stripe availability
try:
    import stripe
    STRIPE_AVAILABLE = True

    # Try multiple version detection methods
    if hasattr(stripe, '__version__'):
        STRIPE_VERSION = stripe.__version__
    elif hasattr(stripe, 'VERSION'):
        STRIPE_VERSION = stripe.VERSION
    else:
        # Fallback to package metadata
        try:
            from importlib.metadata import version
            STRIPE_VERSION = version('stripe')
        except Exception:
            STRIPE_VERSION = 'unknown'
except ImportError:
    STRIPE_AVAILABLE = False
    STRIPE_VERSION = None


@pytest.fixture
async def payment_service(payment_settings, mock_cache_service):
    """Create a payment service instance for testing."""
    if not payment_settings.payments_enabled:
        pytest.skip("Payments not enabled in configuration")

    from app.services.payment_service import PaymentService
    from unittest.mock import patch

    # Mock Stripe to avoid requiring real API keys in tests
    with patch('app.services.payment_service.stripe') as mock_stripe:
        mock_stripe.api_key = None
        service = PaymentService(settings=payment_settings)
        await service.start()
        try:
            yield service
        finally:
            # Cleanup
            if hasattr(service, 'aclose'):
                await service.aclose()


@pytest.mark.integration
@pytest.mark.payment
class TestPaymentSystemIntegration:
    """Integration tests for payment system components."""

    def test_stripe_dependency(self):
        """
        Test that Stripe library is available and properly versioned.

        Verifies:
        - Stripe package can be imported
        - Version information is accessible

        Note: This test will fail if Stripe is not installed via 'uv sync'
        """
        assert STRIPE_AVAILABLE, "Stripe library not installed. Run: uv sync"
        assert STRIPE_VERSION is not None, "Stripe version not detected"
        print(f"✅ Stripe library available (version: {STRIPE_VERSION})")

    @pytest.mark.asyncio
    async def test_payment_configuration(self, payment_settings):
        """Test payment system configuration."""
        # Verify payment settings exist and have correct types
        assert hasattr(payment_settings, 'payments_enabled')
        assert isinstance(payment_settings.payments_enabled, bool)
        assert hasattr(payment_settings, 'subscription_grace_period_days')
        assert payment_settings.subscription_grace_period_days >= 0

        # Check if Stripe keys are configured (not required for tests)
        stripe_configured = (
            hasattr(payment_settings, 'stripe_secret_key') and
            payment_settings.stripe_secret_key is not None and
            hasattr(payment_settings, 'stripe_publishable_key') and
            payment_settings.stripe_publishable_key is not None
        )

        if not stripe_configured:
            print("⚠️  Stripe keys not configured - tests will use mocks")

    @pytest.mark.asyncio
    async def test_payment_services_import(self):
        """Test payment service imports."""
        from app.services.payment_service import PaymentService
        from app.services.subscription_manager import SubscriptionManager
        from app.services.billing_service import BillingService

        assert PaymentService is not None
        assert SubscriptionManager is not None
        assert BillingService is not None

    @pytest.mark.asyncio
    async def test_payment_models(self):
        """Test payment database models."""
        from app.core.db_models import Subscription, PaymentRecord, UsageRecord
        from app.core.db_models import SubscriptionTier, SubscriptionStatus

        assert Subscription is not None
        assert PaymentRecord is not None
        assert UsageRecord is not None
        assert len(list(SubscriptionTier)) > 0
        assert len(list(SubscriptionStatus)) > 0

    @pytest.mark.asyncio
    async def test_payment_router(self):
        """Test payment router configuration."""
        from app.router.payments import router as payments_router
        from app.router.admin_payments import router as admin_payments_router

        assert payments_router is not None
        assert admin_payments_router is not None
        assert payments_router.prefix is not None
        assert admin_payments_router.prefix is not None

    @pytest.mark.asyncio
    async def test_payment_service_initialization(self, payment_settings):
        """Test that PaymentService can be initialized without Stripe keys."""
        from app.services.payment_service import PaymentService
        from unittest.mock import patch

        # Should initialize even without Stripe keys (will be disabled)
        with patch('app.services.payment_service.stripe') as mock_stripe:
            # PaymentService gets settings internally via get_settings()
            service = PaymentService()
            assert service is not None

            # Cleanup
            if hasattr(service, 'aclose'):
                await service.aclose()
