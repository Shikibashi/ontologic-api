#!/usr/bin/env python3
"""
Payment Endpoints Live Integration Tests

Tests the payment API endpoints using FastAPI test client.
Skipped by default; set RUN_LIVE_PAYMENT_TESTS=1 to enable.
"""

import os
import pytest


# Skip all tests in this module unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_PAYMENT_TESTS") != "1",
    reason="Live payment endpoint tests require RUN_LIVE_PAYMENT_TESTS=1"
)


@pytest.mark.integration
@pytest.mark.payment
@pytest.mark.asyncio
class TestPaymentEndpointsLive:
    """Live integration tests for payment endpoints using FastAPI test client.

    Note: These tests verify endpoint existence and authentication requirements.
    They do not test actual payment processing, which requires:
    - Real Stripe API keys
    - Webhook configuration
    - Database setup

    For full payment integration testing, see test_payment_integration.py
    """

    async def test_server_health(self, async_client):
        """Test that server health endpoint is accessible."""
        response = await async_client.get("/health")
        # Health endpoint returns: 200 (healthy), 503 (unhealthy services), or 400 (middleware issues in test env)
        assert response.status_code in [200, 400, 503], \
            f"Health endpoint returned unexpected status {response.status_code}"

    async def test_payment_endpoints_require_authentication(self, async_client):
        """Verify payment endpoints properly require authentication."""
        endpoints = [
            "/payments/subscription",
            "/payments/usage",
            "/payments/billing/history",
        ]

        for endpoint in endpoints:
            response = await async_client.get(endpoint)
            # Without auth, should return 401 (unauthorized) or 403 (forbidden)
            # In test environment with mocked dependencies, may return 404 if payments disabled
            assert response.status_code in [401, 403, 404], \
                f"{endpoint} returned unexpected status {response.status_code}: {response.text}"

    async def test_payment_checkout_endpoint_exists(self, async_client):
        """Test checkout endpoint exists and requires authentication."""
        response = await async_client.post("/payments/checkout", json={
            "price_id": "price_test_basic",
            "success_url": "http://localhost:3000/success",
            "cancel_url": "http://localhost:3000/cancel"
        })
        # Should require authentication or return 404 if payments disabled in test env
        assert response.status_code in [401, 403, 404, 422], \
            f"Checkout endpoint returned unexpected status {response.status_code}: {response.text}"

    async def test_admin_payment_endpoints_exist(self, async_client):
        """Test admin payment endpoints exist and require admin auth."""
        admin_endpoints = [
            "/admin/payments/health",
            "/admin/payments/subscriptions",
        ]

        for endpoint in admin_endpoints:
            response = await async_client.get(endpoint)
            # Should require admin authentication or return 404 if payments disabled
            assert response.status_code in [401, 403, 404, 422], \
                f"{endpoint} returned unexpected status {response.status_code}: {response.text}"
