"""
Enhanced mocking framework for comprehensive service mocking.

Provides async-aware mocks for all services with proper lifecycle management
and database session mocking capabilities.
"""

import asyncio
from typing import Any, Dict, List, Optional, Type, Union, Callable
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.db_models import ChatConversation, ChatMessage, Subscription, PaymentRecord
from app.core.user_models import User
from enum import Enum

class UserRole(str, Enum):
    """User role enum for testing."""
    USER = "user"
    ADMIN = "admin"
    PREMIUM = "premium"


class ServiceMockManager:
    """
    Comprehensive service mocking manager with async-aware capabilities.
    
    Provides centralized mock creation and management for all services
    with proper async handling and resource cleanup.
    """
    
    def __init__(self):
        self.active_mocks: Dict[str, MagicMock] = {}
        self.active_patches: List[Any] = []
        self.async_resources: List[Any] = []
        self._cleanup_callbacks: List[Callable] = []
    
    def register_mock(self, name: str, mock: MagicMock) -> MagicMock:
        """Register a mock for tracking and cleanup."""
        self.active_mocks[name] = mock
        return mock
    
    def register_patch(self, patch_obj: Any) -> Any:
        """Register a patch for cleanup."""
        self.active_patches.append(patch_obj)
        return patch_obj
    
    def register_async_resource(self, resource: Any) -> Any:
        """Register an async resource for cleanup."""
        self.async_resources.append(resource)
        return resource
    
    def add_cleanup_callback(self, callback: Callable) -> None:
        """Add a cleanup callback."""
        self._cleanup_callbacks.append(callback)
    
    async def cleanup_all(self) -> None:
        """Cleanup all registered resources."""
        # Execute cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                print(f"Warning: Cleanup callback failed: {e}")
        
        # Stop patches
        for patch_obj in reversed(self.active_patches):
            try:
                patch_obj.__exit__(None, None, None)
            except Exception:
                pass
        
        # Reset mocks
        for mock in self.active_mocks.values():
            try:
                mock.reset_mock()
            except Exception:
                pass
        
        # Close async resources
        for resource in self.async_resources:
            try:
                if hasattr(resource, 'close'):
                    if asyncio.iscoroutinefunction(resource.close):
                        await resource.close()
                    else:
                        resource.close()
                elif hasattr(resource, 'aclose'):
                    await resource.aclose()
            except Exception:
                pass
        
        # Clear collections
        self.active_mocks.clear()
        self.active_patches.clear()
        self.async_resources.clear()
        self._cleanup_callbacks.clear()
    
    # Service Mock Creation Methods
    
    def create_chat_history_service_mock(self) -> AsyncMock:
        """Create async-aware ChatHistoryService mock."""
        mock = AsyncMock()
        
        # Mock async methods
        mock.store_message = AsyncMock(return_value=self._create_mock_chat_message())
        mock.get_conversation_history = AsyncMock(return_value=[])
        mock.get_conversation = AsyncMock(return_value=self._create_mock_conversation())
        mock.create_conversation = AsyncMock(return_value=self._create_mock_conversation())
        mock.delete_conversation = AsyncMock(return_value=True)
        mock.get_user_conversations = AsyncMock(return_value=[])
        mock.cleanup_expired_conversations = AsyncMock(return_value=0)
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.aclose = AsyncMock()
        
        self.register_mock("chat_history_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_chat_qdrant_service_mock(self) -> AsyncMock:
        """Create async-aware ChatQdrantService mock."""
        mock = AsyncMock()
        
        # Mock async methods
        mock.store_message_embedding = AsyncMock()
        mock.search_similar_messages = AsyncMock(return_value=[])
        mock.get_conversation_context = AsyncMock(return_value=[])
        mock.cleanup_expired_embeddings = AsyncMock(return_value=0)
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.aclose = AsyncMock()
        
        self.register_mock("chat_qdrant_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_payment_service_mock(self, payments_enabled: bool = False) -> MagicMock:
        """Create PaymentService mock with correct attribute access patterns."""
        mock = MagicMock()
        
        # Set correct public attributes (not private ones)
        mock.cache_service = MagicMock()  # Not _cache_service
        mock._payments_enabled = payments_enabled
        mock._stripe_configured = payments_enabled
        
        # Mock async methods
        mock.create_customer = AsyncMock(return_value={"id": "cus_test1234567890"})
        mock.create_subscription = AsyncMock(return_value=self._create_mock_subscription())
        mock.cancel_subscription = AsyncMock(return_value=True)
        mock.process_payment = AsyncMock(return_value={"id": "pi_test123", "status": "succeeded"})
        mock.create_checkout_session = AsyncMock(return_value={"id": "cs_test123", "url": "https://checkout.stripe.com/test"})
        mock.handle_webhook = AsyncMock(return_value={"processed": True})
        mock.get_customer_subscriptions = AsyncMock(return_value=[])
        mock.update_subscription = AsyncMock(return_value=self._create_mock_subscription())
        
        # Remove non-existent method references
        # DO NOT add _get_or_create_customer as it doesn't exist
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.aclose = AsyncMock()
        
        self.register_mock("payment_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_cache_service_mock(self) -> AsyncMock:
        """Create async-aware RedisCacheService mock."""
        mock = AsyncMock()
        
        # Mock async methods
        mock.get = AsyncMock(return_value=None)  # Default cache miss
        mock.set = AsyncMock(return_value=True)
        mock.delete = AsyncMock(return_value=True)
        mock.exists = AsyncMock(return_value=False)
        mock.expire = AsyncMock(return_value=True)
        mock.clear_pattern = AsyncMock(return_value=0)
        mock.get_stats = AsyncMock(return_value={"hits": 0, "misses": 0})
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.close = AsyncMock()
        mock.aclose = AsyncMock()
        
        self.register_mock("cache_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_auth_service_mock(self) -> AsyncMock:
        """Create async-aware AuthService mock."""
        mock = AsyncMock()
        
        # Mock async methods
        mock.authenticate_user = AsyncMock(return_value=self._create_mock_user())
        mock.create_user = AsyncMock(return_value=self._create_mock_user())
        mock.get_user = AsyncMock(return_value=self._create_mock_user())
        mock.update_user = AsyncMock(return_value=self._create_mock_user())
        mock.delete_user = AsyncMock(return_value=True)
        mock.verify_token = AsyncMock(return_value={"user_id": "test_user", "role": "user"})
        mock.generate_token = AsyncMock(return_value="test_token_123")
        mock.refresh_token = AsyncMock(return_value="refreshed_token_123")
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.aclose = AsyncMock()
        
        self.register_mock("auth_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_billing_service_mock(self) -> AsyncMock:
        """Create async-aware BillingService mock."""
        mock = AsyncMock()
        
        # Mock async methods
        mock.track_usage = AsyncMock()
        mock.get_usage_stats = AsyncMock(return_value={"requests": 0, "tokens": 0})
        mock.generate_invoice = AsyncMock(return_value={"id": "inv_test123"})
        mock.process_billing_cycle = AsyncMock(return_value={"processed": 0})
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.aclose = AsyncMock()
        
        self.register_mock("billing_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_expansion_service_mock(self) -> AsyncMock:
        """Create async-aware ExpansionService mock."""
        mock = AsyncMock()
        
        # Mock async methods
        mock.expand_query = AsyncMock(return_value=["expanded query 1", "expanded query 2"])
        mock.hyde_expansion = AsyncMock(return_value="hypothetical document")
        mock.rag_fusion_expansion = AsyncMock(return_value=["fusion query 1", "fusion query 2"])
        mock.self_ask_expansion = AsyncMock(return_value=["self ask query"])
        
        # Mock lifecycle methods
        mock.start = AsyncMock(return_value=mock)
        mock.aclose = AsyncMock()
        
        self.register_mock("expansion_service", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_llm_manager_mock(self) -> MagicMock:
        """Create LLMManager mock with async methods."""
        mock = MagicMock()
        
        # Mock async methods
        mock.aquery = AsyncMock(return_value=self._create_mock_llm_response("Mocked aquery response"))
        mock.achat = AsyncMock(return_value=self._create_mock_llm_response("Mocked achat response"))
        mock.avet = AsyncMock(return_value=self._create_mock_llm_response("Mocked avet response"))
        mock.generate_splade_vector = AsyncMock(return_value={"indices": [1, 2, 3], "values": [0.5, 0.3, 0.2]})
        mock.generate_dense_vector = AsyncMock(return_value=[0.1] * 384)
        mock.get_embedding = AsyncMock(return_value=[0.1] * 384)
        
        # Mock sync methods
        mock.set_llm_context_window = MagicMock()
        mock.set_temperature = MagicMock()
        
        # Mock lifecycle methods
        mock.close = AsyncMock()
        mock.cleanup = AsyncMock()
        
        self.register_mock("llm_manager", mock)
        self.register_async_resource(mock)
        return mock
    
    def create_qdrant_manager_mock(self) -> MagicMock:
        """Create QdrantManager mock with async methods."""
        mock = MagicMock()
        
        # Mock async methods
        mock.query_hybrid = AsyncMock(return_value={})
        mock.gather_points_and_sort = AsyncMock(return_value=[])
        mock.get_collections = AsyncMock(return_value=["Aristotle", "Immanuel Kant", "David Hume"])
        mock.validate_connection = AsyncMock(return_value=True)
        mock.upload_points = AsyncMock(return_value=True)
        mock.delete_points = AsyncMock(return_value=True)
        
        # Mock lifecycle methods
        mock.close = AsyncMock()
        mock.cleanup = AsyncMock()
        
        self.register_mock("qdrant_manager", mock)
        self.register_async_resource(mock)
        return mock
    
    # Helper methods for creating mock data objects
    
    def _create_mock_chat_message(self) -> MagicMock:
        """Create a mock ChatMessage object."""
        mock = MagicMock(spec=ChatMessage)
        mock.id = "msg_test123"
        mock.conversation_id = "conv_test123"
        mock.role = "user"
        mock.content = "Test message content"
        mock.created_at = "2024-01-01T00:00:00Z"
        mock.philosopher_collection = None
        return mock
    
    def _create_mock_conversation(self) -> MagicMock:
        """Create a mock ChatConversation object."""
        mock = MagicMock(spec=ChatConversation)
        mock.id = "conv_test123"
        mock.session_id = "session_test123"
        mock.title = "Test Conversation"
        mock.created_at = "2024-01-01T00:00:00Z"
        mock.updated_at = "2024-01-01T00:00:00Z"
        mock.username = None
        mock.messages = []
        return mock
    
    def _create_mock_user(self, role: str = "user") -> MagicMock:
        """Create a mock User object."""
        mock = MagicMock(spec=User)
        mock.id = 123
        mock.username = "testuser"
        mock.email = "test@example.com"
        mock.is_active = True
        mock.is_superuser = (role == "admin")
        mock.is_verified = True
        mock.created_at = "2024-01-01T00:00:00Z"
        mock.updated_at = "2024-01-01T00:00:00Z"
        return mock
    
    def _create_mock_subscription(self) -> MagicMock:
        """Create a mock Subscription object."""
        mock = MagicMock(spec=Subscription)
        mock.id = "sub_test123"
        mock.user_id = "user_test123"
        mock.stripe_subscription_id = "sub_stripe123"
        mock.tier = "premium"
        mock.status = "active"
        mock.current_period_start = "2024-01-01T00:00:00Z"
        mock.current_period_end = "2024-02-01T00:00:00Z"
        mock.created_at = "2024-01-01T00:00:00Z"
        mock.updated_at = "2024-01-01T00:00:00Z"
        return mock
    
    def _create_mock_llm_response(self, content: str) -> MagicMock:
        """Create a mock LLM response object."""
        mock = MagicMock()
        mock.text = content
        mock.raw = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30
            }
        }
        return mock
    
    # Comprehensive service mocking
    
    def create_all_service_mocks(self, **service_configs) -> Dict[str, Any]:
        """
        Create mocks for all services with optional configuration.
        
        Args:
            **service_configs: Configuration for specific services
                - payments_enabled: bool for payment service
                - cache_enabled: bool for cache service
        
        Returns:
            Dictionary of service name to mock object
        """
        services = {}
        
        # Core services
        services["chat_history"] = self.create_chat_history_service_mock()
        services["chat_qdrant"] = self.create_chat_qdrant_service_mock()
        services["cache"] = self.create_cache_service_mock()
        services["auth"] = self.create_auth_service_mock()
        services["billing"] = self.create_billing_service_mock()
        services["expansion"] = self.create_expansion_service_mock()
        services["llm_manager"] = self.create_llm_manager_mock()
        services["qdrant_manager"] = self.create_qdrant_manager_mock()
        
        # Payment service with configuration
        payments_enabled = service_configs.get("payments_enabled", False)
        services["payment"] = self.create_payment_service_mock(payments_enabled=payments_enabled)
        
        return services