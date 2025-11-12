import pytest
from unittest.mock import AsyncMock, Mock, patch
from fastapi import Request
from app.core.subscription_helpers import check_subscription_access
from app.services.chat_monitoring import chat_monitoring


@pytest.mark.asyncio
async def test_graceful_degradation_with_monitoring_failure(monkeypatch):
    """
    Verify that monitoring failures don't break graceful degradation.
    """
    user = Mock(id=1, subscription_tier="free")
    subscription_manager = AsyncMock()

    # Make subscription check fail
    subscription_manager.check_api_access = AsyncMock(side_effect=Exception("DB error"))

    # Force fail-open mode and payments enabled
    from app.config.settings import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, 'payments_enabled', True, raising=False)
    monkeypatch.setattr(settings, 'subscription_fail_open', True, raising=False)

    # Create a FastAPI Request object
    request = Request(scope={"type": "http"})

    # Make metric recording also fail
    with patch('app.services.chat_monitoring.chat_monitoring.record_counter', side_effect=Exception("Metric error")):
        # Should not raise exception - graceful degradation
        await check_subscription_access(user, subscription_manager, "/test", request)

        # Verify subscription check was attempted
        subscription_manager.check_api_access.assert_called_once()
