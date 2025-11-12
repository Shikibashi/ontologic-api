"""
Unit tests for username support in chat services.

Tests username parameter handling in ChatHistoryService and ChatQdrantService
including storage, retrieval, filtering, and backward compatibility.
"""

import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chat_history_service import ChatHistoryService
from app.services.chat_qdrant_service import ChatQdrantService
from app.core.db_models import ChatConversation, ChatMessage, MessageRole


class TestChatHistoryServiceUsername:
    """Test suite for ChatHistoryService username functionality."""

    @pytest.fixture
    def mock_cache_service(self):
        """Mock cache service for testing."""
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()
        cache.clear_cache = AsyncMock()
        return cache

    @pytest.fixture
    def chat_service(self, mock_cache_service):
        """Create ChatHistoryService instance with mocked cache."""
        return ChatHistoryService(cache_service=mock_cache_service)

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.refresh = AsyncMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def sample_conversation_with_username(self):
        """Create sample conversation with username."""
        return ChatConversation(
            id=1,
            conversation_id="conv_123",
            session_id="session_456",
            username="alice@example.com",
            philosopher_collection="Aristotle",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

    @pytest.fixture
    def sample_message_with_username(self):
        """Create sample message with username."""
        return ChatMessage(
            id=1,
            message_id="msg_123",
            conversation_id="conv_123",
            session_id="session_456",
            username="alice@example.com",
            role=MessageRole.USER,
            content="What is virtue ethics?",
            philosopher_collection="Aristotle",
            created_at=datetime.utcnow()
        )

    async def test_store_message_with_username(self, chat_service, mock_db_session, sample_conversation_with_username):
        """Test storing a message with username parameter."""
        # Mock execute for conversation lookup
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation_with_username
        mock_db_session.execute.return_value = mock_result

        message = await chat_service.store_message(
            session_id="session_456",
            role="user",
            content="What is virtue ethics?",
            philosopher_collection="Aristotle",
            username="alice@example.com",
            session=mock_db_session
        )

        assert message.username == "alice@example.com"
        assert message.session_id == "session_456"
        assert message.content == "What is virtue ethics?"
        mock_db_session.commit.assert_awaited_once()

    async def test_store_message_without_username_backward_compat(self, chat_service, mock_db_session, sample_conversation_with_username):
        """Test storing a message without username (backward compatibility)."""
        # Mock execute for conversation lookup
        sample_conversation_with_username.username = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation_with_username
        mock_db_session.execute.return_value = mock_result

        message = await chat_service.store_message(
            session_id="session_456",
            role="user",
            content="Test message without username",
            session=mock_db_session
        )

        assert message.username is None
        assert message.session_id == "session_456"
        mock_db_session.commit.assert_awaited_once()

    async def test_get_or_create_conversation_with_username(self, chat_service, mock_db_session):
        """Test creating a conversation with username."""
        # Mock execute to return no existing conversation
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        conversation = await chat_service._get_or_create_conversation(
            session_id="session_789",
            philosopher_collection="Kant",
            username="bob@example.com",
            db_session=mock_db_session
        )

        assert conversation.username == "bob@example.com"
        assert conversation.session_id == "session_789"
        assert conversation.philosopher_collection == "Kant"
        mock_db_session.add.assert_called_once()

    async def test_multiple_users_same_session(self, chat_service, mock_db_session):
        """Test that different users can have messages in the same session (if allowed)."""
        # Mock execute for conversation lookup
        mock_result1 = MagicMock()
        mock_result1.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result1

        conversation1 = await chat_service._get_or_create_conversation(
            session_id="shared_session",
            philosopher_collection="Plato",
            username="user1@example.com",
            db_session=mock_db_session
        )

        # Reset mock for second user
        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result2

        conversation2 = await chat_service._get_or_create_conversation(
            session_id="shared_session",
            philosopher_collection="Plato",
            username="user2@example.com",
            db_session=mock_db_session
        )

        # Both conversations should exist with different usernames
        assert conversation1.username == "user1@example.com"
        assert conversation2.username == "user2@example.com"
        assert conversation1.session_id == conversation2.session_id


class TestChatQdrantServiceUsername:
    """Test suite for ChatQdrantService username functionality."""

    @pytest.fixture
    def mock_qdrant_client(self):
        """Mock Qdrant client."""
        client = AsyncMock()
        client.upsert = AsyncMock()
        client.search = AsyncMock(return_value=[])
        client.get_collection = AsyncMock()
        client.create_collection = AsyncMock()
        client.get_collections = AsyncMock()
        return client

    @pytest.fixture
    def mock_llm_manager(self):
        """Mock LLM manager."""
        manager = AsyncMock()
        manager.generate_dense_vector = AsyncMock(return_value=[0.1] * 4096)
        return manager

    @pytest.fixture
    def qdrant_service(self, mock_qdrant_client, mock_llm_manager):
        """Create ChatQdrantService instance with mocked dependencies."""
        return ChatQdrantService(
            qdrant_client=mock_qdrant_client,
            llm_manager=mock_llm_manager
        )

    @pytest.fixture
    def sample_message_with_username(self):
        """Create sample message with username."""
        return ChatMessage(
            id=1,
            message_id="msg_456",
            conversation_id="conv_789",
            session_id="session_012",
            username="charlie@example.com",
            role=MessageRole.USER,
            content="Test message with username",
            created_at=datetime.utcnow()
        )

    async def test_upload_message_includes_username_in_payload(self, qdrant_service, sample_message_with_username, mock_qdrant_client):
        """Test that username is included in Qdrant payload when uploading message."""
        # Mock collection exists
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(name=qdrant_service.collection_name)]
        mock_qdrant_client.get_collections.return_value = mock_collections

        point_ids = await qdrant_service.upload_message_to_qdrant(sample_message_with_username)

        assert len(point_ids) > 0

        # Verify upsert was called
        mock_qdrant_client.upsert.assert_awaited()

        # Get the upsert call arguments
        call_args = mock_qdrant_client.upsert.call_args
        points = call_args.kwargs['points']

        # Check that username is in the payload
        assert len(points) > 0
        first_point = points[0]
        assert first_point.payload['username'] == "charlie@example.com"
        assert first_point.payload['session_id'] == "session_012"

    async def test_upload_message_without_username_backward_compat(self, qdrant_service, sample_message_with_username, mock_qdrant_client):
        """Test uploading message without username (backward compatibility)."""
        sample_message_with_username.username = None

        # Mock collection exists
        mock_collections = MagicMock()
        mock_collections.collections = [MagicMock(name=qdrant_service.collection_name)]
        mock_qdrant_client.get_collections.return_value = mock_collections

        point_ids = await qdrant_service.upload_message_to_qdrant(sample_message_with_username)

        assert len(point_ids) > 0

        # Verify upsert was called
        mock_qdrant_client.upsert.assert_awaited()

        # Get the upsert call arguments
        call_args = mock_qdrant_client.upsert.call_args
        points = call_args.kwargs['points']

        # Check that username is None in the payload
        assert len(points) > 0
        first_point = points[0]
        assert first_point.payload['username'] is None

    def test_payload_structure_includes_username(self):
        """Test that payload structure can include username field."""
        # Test that payload dict accepts username
        payload_with_username = {
            "message_id": "msg_456",
            "conversation_id": "conv_789",
            "session_id": "session_012",
            "username": "diane@example.com",
            "role": "user",
            "content": "Test content",
            "philosopher_collection": "Socrates",
            "created_at": datetime.utcnow().isoformat(),
            "chunk_index": 0,
            "total_chunks": 1
        }

        assert payload_with_username['username'] == "diane@example.com"
        assert payload_with_username['session_id'] == "session_012"

    def test_payload_structure_without_username(self):
        """Test that payload structure works without username (backward compatibility)."""
        # Test that payload dict accepts None username
        payload_without_username = {
            "message_id": "msg_456",
            "conversation_id": "conv_789",
            "session_id": "session_012",
            "username": None,
            "role": "user",
            "content": "Test content",
            "created_at": datetime.utcnow().isoformat(),
            "chunk_index": 0,
            "total_chunks": 1
        }

        assert payload_without_username['username'] is None
        assert payload_without_username['session_id'] == "session_012"
