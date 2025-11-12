"""Tests for security configuration validation."""
import pytest
from app.config.settings import Settings


class TestProductionSecrets:
    """Test production secret validation."""

    def test_default_jwt_secret_rejected_in_production(self):
        """Default JWT secret should fail validation in production."""
        settings = Settings(env="prod")
        is_valid, issues = settings.validate_production_secrets()

        assert not is_valid
        assert any("JWT secret" in issue for issue in issues)

    def test_short_jwt_secret_rejected(self):
        """JWT secrets shorter than 32 chars should fail."""
        settings = Settings(
            env="prod",
            jwt_secret="short_secret_123"
        )
        is_valid, issues = settings.validate_production_secrets()

        assert not is_valid
        assert any("too short" in issue for issue in issues)

    def test_valid_production_secrets_pass(self):
        """Valid production secrets should pass validation."""
        settings = Settings(
            env="prod",
            jwt_secret="a" * 32,  # 32+ char secret
            session_secret="b" * 32,
            payments_enabled=False
        )
        is_valid, issues = settings.validate_production_secrets()

        assert is_valid
        assert len(issues) == 0

    def test_payments_require_stripe_secrets(self):
        """Payments enabled should require Stripe secrets."""
        settings = Settings(
            env="prod",
            jwt_secret="a" * 32,
            payments_enabled=True,
            stripe_secret_key=None,
            stripe_webhook_secret=None
        )
        is_valid, issues = settings.validate_production_secrets()

        assert not is_valid
        assert any("STRIPE_SECRET_KEY" in issue for issue in issues)
        assert any("STRIPE_WEBHOOK_SECRET" in issue for issue in issues)

    def test_dev_environment_allows_defaults(self):
        """Development environment should allow default secrets."""
        settings = Settings(env="dev")
        is_valid, issues = settings.validate_production_secrets()

        # Dev should pass even with defaults
        assert is_valid
        assert len(issues) == 0


class TestCORSConfiguration:
    """Test CORS configuration security."""

    def test_cors_origins_configurable(self, monkeypatch):
        """CORS origins should be configurable via environment variable."""
        # Test that APP_CORS_ORIGINS is recognized and loaded by Settings
        monkeypatch.setenv("APP_CORS_ORIGINS", "https://example.com,https://app.example.com")

        settings = Settings()

        assert len(settings.cors_origins) == 2
        assert "https://example.com" in settings.cors_origins
        assert "https://app.example.com" in settings.cors_origins


class TestSecurityHeaders:
    """Test security headers middleware."""

    def test_security_headers_defined(self):
        """Security headers should be properly defined in SecurityManager."""
        from app.core.security import SecurityManager

        headers = SecurityManager.get_security_headers()

        # Check all critical security headers are present
        assert "X-Content-Type-Options" in headers
        assert headers["X-Content-Type-Options"] == "nosniff"

        assert "X-Frame-Options" in headers
        assert headers["X-Frame-Options"] == "DENY"

        assert "Referrer-Policy" in headers
        assert "Content-Security-Policy" in headers

        # Check HSTS header is present for production
        assert "Strict-Transport-Security" in headers
        assert "max-age=31536000" in headers["Strict-Transport-Security"]
