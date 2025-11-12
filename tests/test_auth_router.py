"""Integration tests for auth router covering success paths and HTTPException propagation."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.router import auth


def test_get_auth_providers_success(test_client):
    # The test_client fixture already provides a mock auth service
    # We just need to configure its return value
    response = test_client.get("/auth/providers")

    assert response.status_code == 200
    payload = response.json()
    # The default mock returns empty providers
    assert "providers" in payload
    assert "oauth_enabled" in payload


def test_create_session_success(test_client):
    # The test_client fixture already provides a mock auth service
    response = test_client.post("/auth/session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "test-session-123"


def test_create_session_unexpected_error(test_client):
    # We need to override the dependency for this specific test
    from app.core import dependencies as deps
    
    mock_auth_service = MagicMock()
    mock_auth_service.create_anonymous_session = AsyncMock(side_effect=RuntimeError("boom"))
    
    # Override the dependency in the test client's app
    test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service
    
    try:
        response = test_client.post("/auth/session")
        assert response.status_code == 500
        assert "Internal Server Error" in response.text
    finally:
        # Restore original override
        mock_auth_service_default = MagicMock()
        mock_auth_service_default.get_available_providers.return_value = {"github": {"name": "GitHub"}}
        mock_auth_service_default.create_anonymous_session = AsyncMock(return_value="test-session-123")
        mock_auth_service_default.get_user_context = AsyncMock(return_value={"session_id": None})
        mock_auth_service_default.delete_session = AsyncMock(return_value=False)
        test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service_default


def test_get_session_info_not_found(test_client):
    # The default mock already returns {"session_id": None}
    response = test_client.get("/auth/session/unknown")

    assert response.status_code == 404
    detail = response.json()["detail"]
    # Enforce structured error format
    assert isinstance(detail, dict), "Session endpoints should use structured error responses"
    assert detail["error"] == "not_found"
    assert "session" in detail["message"].lower()


def test_get_session_info_success(test_client):
    # We need to override the dependency for this specific test
    from app.core import dependencies as deps
    
    async def fake_get_user_context(session_id: str):
        return {
            "session_id": session_id,
            "authenticated": True,
            "user_id": "user-1",
            "provider": "github",
            "features": ["chat_history"],
        }

    mock_auth_service = MagicMock()
    mock_auth_service.get_user_context = AsyncMock(side_effect=fake_get_user_context)
    
    # Override the dependency in the test client's app
    test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service
    
    try:
        response = test_client.get("/auth/session/known")
        assert response.status_code == 200
        payload = response.json()
        assert payload["authenticated"] is True
        assert payload["user_id"] == "user-1"
    finally:
        # Restore original override
        mock_auth_service_default = MagicMock()
        mock_auth_service_default.get_available_providers.return_value = {"github": {"name": "GitHub"}}
        mock_auth_service_default.create_anonymous_session = AsyncMock(return_value="test-session-123")
        mock_auth_service_default.get_user_context = AsyncMock(return_value={"session_id": None})
        mock_auth_service_default.delete_session = AsyncMock(return_value=False)
        test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service_default


def test_logout_session_success(test_client):
    # We need to override the dependency for this specific test
    from app.core import dependencies as deps
    
    mock_auth_service = MagicMock()
    mock_auth_service.delete_session = AsyncMock(return_value=True)
    
    # Override the dependency in the test client's app
    test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service
    
    try:
        response = test_client.delete("/auth/session/known")
        assert response.status_code == 200
        assert response.json()["message"] == "Session destroyed successfully"
    finally:
        # Restore original override
        mock_auth_service_default = MagicMock()
        mock_auth_service_default.get_available_providers.return_value = {"github": {"name": "GitHub"}}
        mock_auth_service_default.create_anonymous_session = AsyncMock(return_value="test-session-123")
        mock_auth_service_default.get_user_context = AsyncMock(return_value={"session_id": None})
        mock_auth_service_default.delete_session = AsyncMock(return_value=False)
        test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service_default


def test_logout_session_not_found(test_client):
    # The default mock already returns False
    response = test_client.delete("/auth/session/missing")

    assert response.status_code == 200
    assert response.json()["message"] == "Session not found or already expired"


def test_oauth_login_disabled(test_client):
    with patch("app.router.auth.get_oauth_enabled", return_value=False):
        response = test_client.get("/auth/github")

    assert response.status_code == 503
    detail = response.json()["detail"]
    # Enforce structured error format
    assert isinstance(detail, dict), "OAuth endpoints should use structured error responses"
    assert detail["error"] == "service_unavailable"
    assert "oauth is disabled" in detail["message"].lower()


def test_oauth_login_unknown_provider(test_client):
    # We need to override the dependency for this specific test
    from app.core import dependencies as deps
    
    mock_auth_service = MagicMock()
    mock_auth_service.get_available_providers.return_value = {"google": {}}
    
    # Override the dependency in the test client's app
    test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service
    
    try:
        with patch("app.router.auth.get_oauth_enabled", return_value=True):
            response = test_client.get("/auth/github")

        assert response.status_code == 404
        detail = response.json()["detail"]
        # Enforce structured error format
        assert isinstance(detail, dict), "OAuth endpoints should use structured error responses"
        assert detail["error"] == "not_found"
        assert "github" in detail["message"].lower()
    finally:
        # Restore original override
        mock_auth_service_default = MagicMock()
        mock_auth_service_default.get_available_providers.return_value = {"github": {"name": "GitHub"}}
        mock_auth_service_default.create_anonymous_session = AsyncMock(return_value="test-session-123")
        mock_auth_service_default.get_user_context = AsyncMock(return_value={"session_id": None})
        mock_auth_service_default.delete_session = AsyncMock(return_value=False)
        test_client.app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service_default


@pytest.mark.parametrize("env_value", ["prod", "production", "PROD", "PRODUCTION"])
def test_oauth_login_blocked_in_production(test_client, env_value):
    """
    Test that OAuth login is blocked in production environments.

    Verifies the production guard returns 503 Service Unavailable
    when settings.env is 'prod', 'production', or case variants.
    """
    # Mock settings to simulate production environment
    mock_settings = MagicMock()
    mock_settings.env = env_value

    mock_auth_service = MagicMock()
    mock_auth_service.get_available_providers.return_value = {"github": {}}

    with patch("app.router.auth.get_oauth_enabled", return_value=True), \
         patch("app.config.settings.get_settings", return_value=mock_settings), \
         patch("app.core.dependencies.get_auth_service", return_value=mock_auth_service):
        response = test_client.get("/auth/github")

    # Should return 503 Service Unavailable in production
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert isinstance(detail, dict), "OAuth login should use structured error responses"
    assert detail["error"] == "service_unavailable"
    assert "production" in detail["message"].lower()
    assert "oauth" in detail["message"].lower()
    # Check service in context
    if "details" in detail and detail["details"]:
        context = detail["details"][0].get("context", {})
        assert context.get("service") == "OAuth Login"


def test_oauth_login_production_guard_logging(test_client, caplog):
    """
    Test that production guard logs a warning when blocking OAuth login.

    Verifies that security events are properly logged for monitoring.
    """
    # Mock settings to simulate production environment
    mock_settings = MagicMock()
    mock_settings.env = "prod"

    mock_auth_service = MagicMock()
    mock_auth_service.get_available_providers.return_value = {"github": {}}

    with caplog.at_level(logging.WARNING), \
         patch("app.router.auth.get_oauth_enabled", return_value=True), \
         patch("app.config.settings.get_settings", return_value=mock_settings), \
         patch("app.core.dependencies.get_auth_service", return_value=mock_auth_service):
        response = test_client.get("/auth/github")

    # Should return 503
    assert response.status_code == 503

    # Should log a warning about the blocked attempt
    log_text = caplog.text.lower()
    assert "oauth login attempted in production" in log_text or "blocked" in log_text


def test_oauth_login_production_guard_with_oauth_disabled(test_client):
    """
    Test that production guard is checked before OAuth disabled check.

    Verifies the endpoint returns 503 for production guard even when
    OAuth is disabled (production check happens first).
    """
    # Mock settings to simulate production environment
    mock_settings = MagicMock()
    mock_settings.env = "prod"

    mock_auth_service = MagicMock()
    mock_auth_service.get_available_providers.return_value = {"github": {}}

    with patch("app.router.auth.get_oauth_enabled", return_value=False), \
         patch("app.config.settings.get_settings", return_value=mock_settings), \
         patch("app.core.dependencies.get_auth_service", return_value=mock_auth_service):
        response = test_client.get("/auth/github")

    # Should return 503 for production guard (checked first)
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert isinstance(detail, dict), "OAuth login should use structured error responses"
    # Should mention production, not just OAuth disabled
    assert "production" in detail["message"].lower()


def test_oauth_callback_success_path(test_client):
    with patch("app.router.auth.get_oauth_enabled", return_value=True):
        response = test_client.get("/auth/github/callback", params={"code": "test-code"})

    assert response.status_code == 501
    detail = response.json()["detail"]
    if isinstance(detail, dict):
        assert "oauth callback not implemented" in detail["message"].lower()
    else:
        assert response.json()["detail"].startswith("OAuth callback not implemented")


def test_oauth_callback_missing_code(test_client):
    with patch("app.router.auth.get_oauth_enabled", return_value=True):
        response = test_client.get("/auth/github/callback")

    assert response.status_code == 400
    detail = response.json()["detail"]

    # Enforce new structured error format
    assert isinstance(detail, dict), "OAuth callback should use structured error responses"
    assert detail["error"] == "validation_error"
    # Check field in details array
    if "details" in detail and detail["details"]:
        assert detail["details"][0].get("field") == "code"
        assert "authorization code" in detail["details"][0]["message"].lower()
    else:
        # Fallback check for message format
        assert "validation" in detail["message"].lower()


@pytest.mark.parametrize("env_value", ["prod", "production", "PROD", "PRODUCTION"])
def test_oauth_callback_blocked_in_production(test_client, env_value):
    """
    Test that OAuth callback is blocked in production environments.

    Verifies the production guard returns 503 Service Unavailable
    when settings.env is 'prod', 'production', or case variants.
    """
    # Mock settings to simulate production environment
    mock_settings = MagicMock()
    mock_settings.env = env_value

    with patch("app.router.auth.get_oauth_enabled", return_value=True), \
         patch("app.config.settings.get_settings", return_value=mock_settings):
        response = test_client.get(
            "/auth/github/callback",
            params={"code": "test-authorization-code"}
        )

    # Should return 503 Service Unavailable in production
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert isinstance(detail, dict), "OAuth callback should use structured error responses"
    assert detail["error"] == "service_unavailable"
    assert "production" in detail["message"].lower()
    assert "oauth" in detail["message"].lower()
    # Check service in context
    if "details" in detail and detail["details"]:
        context = detail["details"][0].get("context", {})
        assert context.get("service") == "OAuth Callback"


def test_oauth_callback_allowed_in_development(test_client):
    """
    Test that OAuth callback returns 501 Not Implemented in development.

    Verifies the production guard allows the endpoint in non-production
    environments, but it still returns 501 because OAuth is not implemented.
    """
    # Mock settings to simulate development environment
    mock_settings = MagicMock()
    mock_settings.env = "dev"

    with patch("app.router.auth.get_oauth_enabled", return_value=True), \
         patch("app.config.settings.get_settings", return_value=mock_settings):
        response = test_client.get(
            "/auth/github/callback",
            params={"code": "test-authorization-code"}
        )

    # Should return 501 Not Implemented in development
    assert response.status_code == 501

    detail = response.json()["detail"]
    assert isinstance(detail, dict), "OAuth callback should use structured error responses"
    assert "not implemented" in detail["message"].lower()
    assert "oauth callback" in detail["message"].lower()


def test_oauth_callback_production_guard_logging(test_client, caplog):
    """
    Test that production guard logs a warning when blocking OAuth callback.

    Verifies that security events are properly logged for monitoring.
    """
    # Mock settings to simulate production environment
    mock_settings = MagicMock()
    mock_settings.env = "prod"

    with caplog.at_level(logging.WARNING), \
         patch("app.router.auth.get_oauth_enabled", return_value=True), \
         patch("app.config.settings.get_settings", return_value=mock_settings):
        response = test_client.get(
            "/auth/github/callback",
            params={"code": "test-authorization-code"}
        )

    # Should return 503
    assert response.status_code == 503

    # Should log a warning about the blocked attempt
    log_text = caplog.text.lower()
    assert "oauth callback attempted in production" in log_text or "blocked" in log_text


def test_oauth_callback_production_guard_with_oauth_disabled(test_client):
    """
    Test that production guard is checked before OAuth disabled check.

    Verifies the endpoint returns 503 for production guard even when OAuth is disabled
    (production check happens first).
    """
    # Mock settings to simulate production environment
    mock_settings = MagicMock()
    mock_settings.env = "prod"

    with patch("app.router.auth.get_oauth_enabled", return_value=False), \
         patch("app.config.settings.get_settings", return_value=mock_settings):
        response = test_client.get(
            "/auth/github/callback",
            params={"code": "test-authorization-code"}
        )

    # Should return 503 for production guard (production guard checked first)
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert isinstance(detail, dict), "OAuth callback should use structured error responses"
    # Production guard is checked first, so we get production error message
    assert "production" in detail["message"].lower()


def test_oauth_callback_oauth_disabled_in_dev(test_client):
    """
    Test OAuth disabled check in development environment.

    Verifies that when OAuth is disabled in dev, the endpoint returns
    503 with OAuth disabled message (not production guard message).
    """
    # Mock settings to simulate development environment
    mock_settings = MagicMock()
    mock_settings.env = "dev"

    with patch("app.router.auth.get_oauth_enabled", return_value=False), \
         patch("app.config.settings.get_settings", return_value=mock_settings):
        response = test_client.get(
            "/auth/github/callback",
            params={"code": "test-authorization-code"}
        )

    # Should return 503 for OAuth disabled
    assert response.status_code == 503

    detail = response.json()["detail"]
    assert isinstance(detail, dict), "OAuth callback should use structured error responses"
    assert detail["error"] == "service_unavailable"
    assert "oauth is disabled in configuration" in detail["message"].lower()
