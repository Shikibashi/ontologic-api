"""Tests for Stripe webhook security."""
import pytest
import stripe
from unittest.mock import Mock, patch
from app.router.payments import handle_stripe_webhook


class TestWebhookSignatureValidation:
    """Test webhook signature verification."""

    @pytest.mark.asyncio
    async def test_missing_signature_rejected(self, test_client):
        """Webhook without signature header should be rejected."""
        response = await test_client.post(
            "/payments/webhooks/stripe",
            json={"type": "test.event"},
            headers={}  # No stripe-signature header
        )

        assert response.status_code == 400
        assert "signature" in response.json()["detail"]["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, test_client):
        """Webhook with invalid signature should be rejected."""
        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.side_effect = stripe.error.SignatureVerificationError(
                "Invalid signature", "sig_header"
            )

            response = await test_client.post(
                "/payments/webhooks/stripe",
                json={"type": "test.event"},
                headers={"stripe-signature": "invalid_sig"}
            )

            assert response.status_code == 400
            assert "signature" in response.json()["detail"]["error"].lower()

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self, test_client, mock_payment_service):
        """Webhook with valid signature should be processed."""
        event = {
            "id": "evt_test_123",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_123"}}
        }

        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.return_value = event
            mock_payment_service.check_webhook_processed.return_value = False

            response = await test_client.post(
                "/payments/webhooks/stripe",
                json=event,
                headers={"stripe-signature": "valid_sig"}
            )

            assert response.status_code == 200
            assert response.json()["received"] is True


class TestWebhookIdempotency:
    """Test webhook idempotency handling."""

    @pytest.mark.asyncio
    async def test_duplicate_event_not_reprocessed(self, test_client, mock_payment_service):
        """Duplicate webhook events should not be reprocessed."""
        event = {
            "id": "evt_test_123",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_123"}}
        }

        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.return_value = event
            mock_payment_service.check_webhook_processed.return_value = True  # Already processed

            response = await test_client.post(
                "/payments/webhooks/stripe",
                json=event,
                headers={"stripe-signature": "valid_sig"}
            )

            assert response.status_code == 200
            assert response.json()["processed"] is True
            # Verify event handler was NOT called again
            mock_payment_service.sync_subscription_from_stripe.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_event_processed_and_marked(self, test_client, mock_payment_service):
        """New webhook events should be processed and marked as processed."""
        event = {
            "id": "evt_test_456",
            "type": "customer.subscription.created",
            "data": {"object": {"id": "sub_456"}}
        }

        with patch('stripe.Webhook.construct_event') as mock_construct:
            mock_construct.return_value = event
            mock_payment_service.check_webhook_processed.return_value = False  # New event

            response = await test_client.post(
                "/payments/webhooks/stripe",
                json=event,
                headers={"stripe-signature": "valid_sig"}
            )

            assert response.status_code == 200
            # Verify event was marked as processed
            mock_payment_service.mark_webhook_processed.assert_called_once_with(
                "evt_test_456", "customer.subscription.created"
            )
