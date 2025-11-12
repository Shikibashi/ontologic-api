"""
Integration test for the enhanced mocking framework.

Verifies that all components of the mocking framework work together
and can be used in actual test scenarios.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.helpers.test_mock_manager import ServiceMockManager
from tests.helpers.async_mock_utilities import AsyncMockUtilities
from tests.helpers.database_mock_manager import DatabaseMockManager
from tests.helpers.auth_mock_helpers import AuthMockHelper, create_test_auth_context


class TestMockingFrameworkIntegration:
    """Test the enhanced mocking framework integration."""
    
    def test_service_mock_manager_creates_all_services(self, service_mock_manager: ServiceMockManager):
        """Test that ServiceMockManager creates all required service mocks."""
        services = service_mock_manager.create_all_service_mocks()
        
        expected_services = [
            "chat_history", "chat_qdrant", "cache", "auth", "billing",
            "expansion", "llm_manager", "qdrant_manager", "payment"
        ]
        
        for service_name in expected_services:
            assert service_name in services
            assert services[service_name] is not None
        
        # Verify async methods are properly mocked
        assert hasattr(services["chat_history"], "store_message")
        assert isinstance(services["chat_history"].store_message, AsyncMock)
        
        # Verify payment service has correct attributes
        payment_service = services["payment"]
        assert hasattr(payment_service, "cache_service")  # Not _cache_service
        assert hasattr(payment_service, "_payments_enabled")
    
    def test_database_mock_manager_creates_session(self, database_mock_manager: DatabaseMockManager):
        """Test that DatabaseMockManager creates proper session mocks."""
        session_mock = database_mock_manager.create_async_session_mock("test_session")
        
        # Verify session has required methods
        assert hasattr(session_mock, "commit")
        assert hasattr(session_mock, "rollback")
        assert hasattr(session_mock, "execute")
        assert hasattr(session_mock, "scalar")
        
        # Verify async methods are AsyncMock
        assert isinstance(session_mock.commit, AsyncMock)
        assert isinstance(session_mock.execute, AsyncMock)
        
        # Test query result configuration
        database_mock_manager.configure_query_results("test_session", "scalar", "test_result")
        assert session_mock.scalar.return_value == "test_result"
    
    def test_auth_mock_helper_creates_users(self, auth_mock_helper: AuthMockHelper):
        """Test that AuthMockHelper creates proper user objects."""
        # Test regular user
        user = auth_mock_helper.create_test_user()
        assert user.username == "testuser"
        assert user.is_active is True
        assert user.is_superuser is False
        
        # Test admin user
        admin = auth_mock_helper.create_admin_user()
        assert admin.is_superuser is True
        
        # Test JWT token generation
        token = auth_mock_helper.generate_jwt_token(user)
        assert isinstance(token, str)
        assert len(token) > 100  # JWT tokens are long
    
    def test_auth_context_creation(self):
        """Test that auth context creation works for different user types."""
        # Test admin context
        admin_context = create_test_auth_context("admin")
        assert admin_context["user"].is_superuser is True
        assert "Bearer " in admin_context["headers"]["Authorization"]
        
        # Test regular user context
        user_context = create_test_auth_context("regular")
        assert user_context["user"].is_superuser is False
        assert "Bearer " in user_context["headers"]["Authorization"]
        
        # Test unauthenticated context
        unauth_context = create_test_auth_context("unauthenticated")
        assert unauth_context["user"] is None
        assert unauth_context["headers"] == {}
    
    def test_async_mock_utilities(self):
        """Test async mock utilities work correctly."""
        utils = AsyncMockUtilities()
        
        # Create a test service class with a method
        class TestService:
            def test_method(self):
                pass
        
        # Test async service mock creation
        mock = utils.create_async_service_mock(
            TestService,
            test_method={"return_value": "test_result"}
        )
        
        assert isinstance(mock, AsyncMock)
        assert mock.test_method.return_value == "test_result"
        
        # Test async context manager mock
        context_mock = utils.create_async_context_manager_mock("context_result")
        assert hasattr(context_mock, "__aenter__")
        assert hasattr(context_mock, "__aexit__")
    
    async def test_comprehensive_service_mocks_fixture(self, comprehensive_service_mocks):
        """Test that the comprehensive service mocks fixture works."""
        services = comprehensive_service_mocks
        
        # Test that we can call async methods
        result = await services["chat_history"].store_message(
            session_id="test",
            role="user",
            content="test message"
        )
        
        # Should return a mock chat message
        assert result is not None
        
        # Test cache service
        cache_result = await services["cache"].get("test_key")
        assert cache_result is None  # Default cache miss
        
        # Test LLM manager
        llm_result = await services["llm_manager"].aquery("test query")
        assert llm_result is not None
    
    def test_mock_cleanup(self, service_mock_manager: ServiceMockManager):
        """Test that mock cleanup works properly."""
        # Create some mocks
        services = service_mock_manager.create_all_service_mocks()
        
        # Register some resources
        service_mock_manager.register_mock("test_mock", MagicMock())
        service_mock_manager.register_async_resource(AsyncMock())
        
        # Verify resources are tracked
        assert len(service_mock_manager.active_mocks) > 0
        assert len(service_mock_manager.async_resources) > 0
        
        # Note: Cleanup happens automatically via fixture teardown