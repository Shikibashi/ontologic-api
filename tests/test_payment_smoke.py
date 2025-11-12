#!/usr/bin/env python3
"""Payment System Smoke Tests

Quick validation tests that verify payment system components are properly
installed and configured, without requiring Stripe API keys or live services.

These tests should always pass if the payment system is correctly set up.
"""

import pytest
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.smoke
@pytest.mark.payment
class TestPaymentSystemSmoke:
    """Smoke tests for payment system basic functionality."""

    def test_stripe_package_installed(self):
        """Verify Stripe package is installed."""
        try:
            import stripe
            assert stripe is not None
            print(f"✅ Stripe package installed")
        except ImportError as e:
            pytest.fail(f"Stripe package not installed: {e}. Run: uv sync")

    def test_payment_models_importable(self):
        """Verify payment database models can be imported."""
        from app.core.db_models import (
            Subscription,
            PaymentRecord,
            UsageRecord,
            SubscriptionTier,
            SubscriptionStatus,
        )

        assert Subscription is not None
        assert PaymentRecord is not None
        assert UsageRecord is not None
        assert len(list(SubscriptionTier)) == 4  # FREE, BASIC, PREMIUM, ACADEMIC
        assert len(list(SubscriptionStatus)) >= 5  # ACTIVE, CANCELED, etc.
        print("✅ Payment models importable")

    def test_payment_services_importable(self):
        """Verify payment services can be imported."""
        from app.services.payment_service import PaymentService
        from app.services.subscription_manager import SubscriptionManager
        from app.services.billing_service import BillingService

        assert PaymentService is not None
        assert SubscriptionManager is not None
        assert BillingService is not None
        print("✅ Payment services importable")

    def test_payment_routers_importable(self):
        """Verify payment routers can be imported."""
        from app.router.payments import router as payments_router
        from app.router.admin_payments import router as admin_payments_router

        assert payments_router is not None
        assert admin_payments_router is not None
        assert payments_router.prefix == "/payments"
        assert admin_payments_router.prefix == "/admin/payments"
        print("✅ Payment routers importable")

    def test_payment_configuration_exists(self):
        """Verify payment configuration is accessible."""
        from app.config.settings import get_settings

        settings = get_settings()
        assert hasattr(settings, 'payments_enabled')
        assert hasattr(settings, 'subscription_grace_period_days')
        assert hasattr(settings, 'stripe_secret_key')
        assert hasattr(settings, 'stripe_publishable_key')
        print("✅ Payment configuration accessible")

    @pytest.mark.asyncio
    async def test_payment_service_can_initialize(self):
        """Verify PaymentService can be instantiated (even without Stripe keys)."""
        from app.services.payment_service import PaymentService
        from unittest.mock import patch

        # Mock stripe to avoid requiring real API keys
        with patch('app.services.payment_service.stripe'):
            # PaymentService gets settings internally via get_settings()
            service = PaymentService()
            assert service is not None
            print("✅ PaymentService can be instantiated")

    def test_subscription_tiers_configured(self):
        """Verify subscription tiers are properly configured."""
        from app.core.db_models import SubscriptionTier

        tiers = list(SubscriptionTier)
        tier_names = [tier.value for tier in tiers]

        assert 'free' in tier_names
        assert 'basic' in tier_names
        assert 'premium' in tier_names
        assert 'academic' in tier_names
        print(f"✅ Subscription tiers configured: {tier_names}")

    def test_payment_error_responses_exist(self):
        """Verify payment-related error response functions exist."""
        from app.core.error_responses import (
            create_error_response,
            create_validation_error,
            create_not_found_error,
            create_forbidden_error,
        )

        assert create_error_response is not None
        assert create_validation_error is not None
        assert create_not_found_error is not None
        assert create_forbidden_error is not None
        print("✅ Payment error responses exist")


if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v", "-m", "smoke"])
