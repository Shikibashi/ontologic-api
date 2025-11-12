"""
Unit tests for PaymentService._normalize_customer_id helper method.

Comprehensive test coverage for customer ID normalization including
edge cases, validation, and error handling.
"""

import pytest
from unittest.mock import MagicMock

from app.services.payment_service import PaymentService, PaymentException
from app.core.user_models import User


@pytest.fixture
def payment_service():
    """Create PaymentService instance for testing."""
    service = PaymentService()
    # Enable payments for testing
    service._payments_enabled = True
    service._stripe_configured = True
    return service


class TestCustomerNormalization:
    """Test _normalize_customer_id helper method."""

    def test_normalize_user_with_valid_customer_id(self, payment_service):
        """Test normalizing User object with valid Stripe customer ID."""
        mock_user = MagicMock(spec=User)
        mock_user.id = 123
        mock_user.stripe_customer_id = "cus_test12345678904567890"

        customer_id, user_id = payment_service._normalize_customer_id(mock_user)

        assert customer_id == "cus_test12345678904567890"
        assert user_id == 123

    def test_normalize_user_without_customer_id(self, payment_service):
        """Test normalizing User object without Stripe customer ID raises error."""
        mock_user = MagicMock(spec=User)
        mock_user.id = 123
        mock_user.stripe_customer_id = None

        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id(mock_user)

        assert "User 123 does not have a Stripe customer ID" in str(exc_info.value)
        assert "create_stripe_customer" in str(exc_info.value)

    def test_normalize_user_with_empty_customer_id(self, payment_service):
        """Test normalizing User with empty customer ID string."""
        mock_user = MagicMock(spec=User)
        mock_user.id = 456
        mock_user.stripe_customer_id = "   "

        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id(mock_user)

        assert "User 456 does not have a Stripe customer ID" in str(exc_info.value)

    def test_normalize_valid_customer_id_string(self, payment_service):
        """Test normalizing valid Stripe customer ID string."""
        customer_id, user_id = payment_service._normalize_customer_id("cus_test12345678904567890")

        assert customer_id == "cus_test12345678904567890"
        assert user_id is None

    def test_normalize_customer_id_with_whitespace(self, payment_service):
        """Test normalizing customer ID string with leading/trailing whitespace."""
        customer_id, user_id = payment_service._normalize_customer_id("  cus_test12345678904567890  ")

        assert customer_id == "cus_test12345678904567890"
        assert user_id is None

    def test_normalize_empty_customer_id_string(self, payment_service):
        """Test normalizing empty customer ID string raises error."""
        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id("")

        assert "required and cannot be empty" in str(exc_info.value)
        assert "cus_" in str(exc_info.value)

    def test_normalize_whitespace_only_customer_id(self, payment_service):
        """Test normalizing whitespace-only customer ID raises error."""
        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id("   ")

        assert "required and cannot be empty" in str(exc_info.value)

    def test_normalize_invalid_customer_id_format_no_prefix(self, payment_service):
        """Test normalizing customer ID without 'cus_' prefix raises error."""
        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id("invalid_1234567890")

        assert "Invalid Stripe customer ID format" in str(exc_info.value)
        assert "must start with 'cus_'" in str(exc_info.value)

    def test_normalize_invalid_customer_id_too_short(self, payment_service):
        """Test normalizing customer ID that's too short raises error."""
        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id("cus_123")

        assert "Invalid Stripe customer ID format" in str(exc_info.value)
        assert "at least 14 characters" in str(exc_info.value)

    def test_normalize_customer_id_case_sensitivity(self, payment_service):
        """Test that customer IDs are case-sensitive (Stripe requirement)."""
        # Should work with exact case
        customer_id, _ = payment_service._normalize_customer_id("cus_ABC1234567890")
        assert customer_id == "cus_ABC1234567890"

        # Should reject uppercase prefix
        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id("CUS_ABC1234567890")
        assert "must start with 'cus_'" in str(exc_info.value)

    def test_normalize_customer_id_exact_minimum_length(self, payment_service):
        """Test customer ID with exact minimum length (14 characters)."""
        customer_id, _ = payment_service._normalize_customer_id("cus_1234567890")
        assert customer_id == "cus_1234567890"
        assert len(customer_id) == 14

    def test_normalize_customer_id_longer_than_minimum(self, payment_service):
        """Test customer ID longer than minimum length."""
        long_id = "cus_" + "a" * 20
        customer_id, _ = payment_service._normalize_customer_id(long_id)
        assert customer_id == long_id

    def test_normalize_user_with_valid_id_and_whitespace(self, payment_service):
        """Test User with customer ID containing whitespace is normalized."""
        mock_user = MagicMock(spec=User)
        mock_user.id = 789
        mock_user.stripe_customer_id = "  cus_test12345678904567890  "

        customer_id, user_id = payment_service._normalize_customer_id(mock_user)

        assert customer_id == "cus_test12345678904567890"
        assert user_id == 789

    def test_normalize_special_characters_in_id(self, payment_service):
        """Test customer ID with special characters (valid Stripe format)."""
        # Stripe IDs can contain alphanumeric characters
        customer_id, _ = payment_service._normalize_customer_id("cus_TestID123XYZ")
        assert customer_id == "cus_TestID123XYZ"

    def test_normalize_user_with_invalid_format(self, payment_service):
        """Test User with invalid customer ID format raises error."""
        mock_user = MagicMock(spec=User)
        mock_user.id = 999
        mock_user.stripe_customer_id = "invalid_customer_id"

        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id(mock_user)

        assert "Invalid Stripe customer ID format" in str(exc_info.value)
        assert "must start with 'cus_'" in str(exc_info.value)

    def test_error_messages_are_actionable(self, payment_service):
        """Verify error messages provide actionable guidance."""
        mock_user = MagicMock(spec=User)
        mock_user.id = 111
        mock_user.stripe_customer_id = None

        with pytest.raises(PaymentException) as exc_info:
            payment_service._normalize_customer_id(mock_user)

        error_msg = str(exc_info.value)
        # Verify error message includes guidance
        assert "create_stripe_customer" in error_msg
        assert "111" in error_msg  # Includes user ID for context
