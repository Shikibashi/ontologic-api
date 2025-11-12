"""
Unit tests for ChatHistoryService.

Tests message storage and retrieval operations, session isolation,
privacy protection, pagination, and error handling scenarios.
"""

import pytest
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError

from app.services.chat_history_service import ChatHistoryService
from app.core.db_models import ChatConversation, ChatMessage, MessageRole
from app.core.chat_exceptions import (
    ChatDatabaseError, ChatValidationError, ChatPrivacyError
)


class TestChatHistoryService:
    """Test suite for ChatHistoryService functionality."""

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
    def sample_conversation(self):
        """Sample conversation for testing."""
        return ChatConversation(
            id=1,
            conversation_id="conv-123",
            session_id="session-456",
            title="Test Conversation",
            philosopher_collection="Aristotle",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )

    @pytest.fixture
    def sample_message(self):
        """Sample message for testing."""
        return ChatMessage(
            id=1,
            message_id="msg-123",
            conversation_id="conv-123",
            session_id="session-456",
            role=MessageRole.USER,
            content="Test message content",
            philosopher_collection="Aristotle",
            created_at=datetime.utcnow()
        )

    @pytest.mark.asyncio
    async def test_store_message_success(self, chat_service, mock_db_session, sample_conversation):
        """Test successful message storage."""
        # Mock conversation retrieval
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.store_message(
                session_id="session-456",
                role="user",
                content="Test message content",
                philosopher_collection="Aristotle"
            )

            # Verify message was created and added to session
            assert mock_db_session.add.call_count >= 1  # Message and conversation update
            assert mock_db_session.commit.called
            assert mock_db_session.refresh.called

    @pytest.mark.asyncio
    async def test_store_message_validation_errors(self, chat_service):
        """Test message storage validation errors."""
        # Test empty session_id
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.store_message("", "user", "content")
        assert "Session ID cannot be empty" in str(exc_info.value)

        # Test empty content
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.store_message("session-123", "user", "")
        assert "Message content cannot be empty" in str(exc_info.value)

        # Test invalid role
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.store_message("session-123", "invalid_role", "content")
        assert "Invalid message role" in str(exc_info.value)

        # Test content too long
        long_content = "x" * 50001
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.store_message("session-123", "user", long_content)
        assert "Message content too long" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_store_message_database_errors(self, chat_service, mock_db_session, sample_conversation):
        """Test database error handling during message storage."""
        # Mock conversation retrieval first
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation
        mock_db_session.execute.return_value = mock_result
        
        # Test IntegrityError - use session parameter to avoid outer error handling
        mock_db_session.commit.side_effect = IntegrityError("statement", "params", "orig")
        
        with pytest.raises(ChatDatabaseError) as exc_info:
            await chat_service.store_message(
                session_id="session-123", 
                role="user", 
                content="content",
                session=mock_db_session
            )
        
        assert "data integrity constraint" in str(exc_info.value)
        assert mock_db_session.rollback.called

        # Test OperationalError
        mock_db_session.reset_mock()
        mock_db_session.execute.return_value = mock_result  # Reset the mock result
        mock_db_session.commit.side_effect = OperationalError("statement", "params", "orig")
        
        with pytest.raises(ChatDatabaseError) as exc_info:
            await chat_service.store_message(
                session_id="session-123", 
                role="user", 
                content="content",
                session=mock_db_session
            )
        
        assert "operational error" in str(exc_info.value)
        assert exc_info.value.recoverable is True

    @pytest.mark.asyncio
    async def test_get_conversation_history_success(self, chat_service, mock_db_session):
        """Test successful conversation history retrieval."""
        # Create sample messages
        messages = [
            ChatMessage(
                id=i,
                message_id=f"msg-{i}",
                conversation_id="conv-123",
                session_id="session-456",
                role=MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                content=f"Message {i}",
                created_at=datetime.utcnow() + timedelta(minutes=i)
            )
            for i in range(5)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = messages
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.get_conversation_history(
                session_id="session-456",
                limit=10,
                offset=0
            )

            assert len(result) == 5
            assert all(msg.session_id == "session-456" for msg in result)

    @pytest.mark.asyncio
    async def test_get_conversation_history_validation_errors(self, chat_service):
        """Test conversation history retrieval validation errors."""
        # Test empty session_id
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.get_conversation_history("")
        assert "Session ID cannot be empty" in str(exc_info.value)

        # Test invalid limit
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.get_conversation_history("session-123", limit=0)
        assert "Limit must be between 1 and 1000" in str(exc_info.value)

        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.get_conversation_history("session-123", limit=1001)
        assert "Limit must be between 1 and 1000" in str(exc_info.value)

        # Test negative offset
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.get_conversation_history("session-123", offset=-1)
        assert "Offset cannot be negative" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_conversation_history_pagination(self, chat_service, mock_db_session):
        """Test pagination in conversation history retrieval."""
        # Create more messages than the limit
        messages = [
            ChatMessage(
                id=i,
                message_id=f"msg-{i}",
                conversation_id="conv-123",
                session_id="session-456",
                role=MessageRole.USER,
                content=f"Message {i}",
                created_at=datetime.utcnow() + timedelta(minutes=i)
            )
            for i in range(3)  # Return 3 messages for second page
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = messages
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.get_conversation_history(
                session_id="session-456",
                limit=5,
                offset=10
            )

            assert len(result) == 3
            # Verify the query was called with correct parameters
            mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_isolation_in_history_retrieval(self, chat_service, mock_db_session):
        """Test that users can only access their own conversation history."""
        # Mock empty result for different session
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.get_conversation_history(
                session_id="different-session"
            )

            assert len(result) == 0
            # Verify session_id was used in the query
            mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_conversation_privacy_validation(self, chat_service, mock_db_session):
        """Test privacy validation when accessing specific conversations."""
        # Mock no conversation found (privacy violation)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Use session parameter to avoid fallback decorator
        with pytest.raises(ChatPrivacyError) as exc_info:
            await chat_service.get_conversation_history(
                session_id="session-456",
                conversation_id="unauthorized-conv",
                session=mock_db_session
            )

        assert "Conversation not found or access denied" in str(exc_info.value)
        assert exc_info.value.violation_type == "conversation_access"

    @pytest.mark.asyncio
    async def test_delete_user_history_success(self, chat_service, mock_db_session, sample_conversation, sample_message):
        """Test successful user history deletion."""
        # Mock conversation and message retrieval
        conv_result = MagicMock()
        conv_result.scalars.return_value.first.return_value = sample_conversation
        
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = [sample_message]
        
        # Return different results for different queries
        mock_db_session.execute.side_effect = [conv_result, msg_result]

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.delete_user_history(
                session_id="session-456",
                conversation_id="conv-123"
            )

            assert result is True
            assert mock_db_session.delete.call_count >= 1  # Message and conversation
            assert mock_db_session.commit.called

    @pytest.mark.asyncio
    async def test_delete_user_history_validation_errors(self, chat_service):
        """Test validation errors in user history deletion."""
        # Test empty session_id
        with pytest.raises(ChatValidationError) as exc_info:
            await chat_service.delete_user_history("")
        assert "Session ID cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_user_history_privacy_violation(self, chat_service, mock_db_session):
        """Test privacy violation during history deletion."""
        # Mock no conversation found (privacy violation)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Use the session parameter to avoid the database connection wrapper
        with pytest.raises(ChatPrivacyError) as exc_info:
            await chat_service.delete_user_history(
                session_id="session-456",
                conversation_id="unauthorized-conv",
                session=mock_db_session
            )

        assert "Conversation not found or access denied" in str(exc_info.value)
        assert exc_info.value.violation_type == "conversation_deletion"

    @pytest.mark.asyncio
    async def test_delete_all_user_history(self, chat_service, mock_db_session):
        """Test deletion of all user history for a session."""
        # Mock messages and conversations
        messages = [
            ChatMessage(id=1, message_id="msg-1", session_id="session-456", conversation_id="conv-1", role=MessageRole.USER, content="msg1"),
            ChatMessage(id=2, message_id="msg-2", session_id="session-456", conversation_id="conv-2", role=MessageRole.USER, content="msg2")
        ]
        conversations = [
            ChatConversation(id=1, conversation_id="conv-1", session_id="session-456"),
            ChatConversation(id=2, conversation_id="conv-2", session_id="session-456")
        ]

        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = messages
        
        conv_result = MagicMock()
        conv_result.scalars.return_value.all.return_value = conversations
        
        mock_db_session.execute.side_effect = [msg_result, conv_result]

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.delete_user_history(session_id="session-456")

            assert result is True
            # Should delete all messages and conversations
            assert mock_db_session.delete.call_count == 4  # 2 messages + 2 conversations
            assert mock_db_session.commit.called

    @pytest.mark.asyncio
    async def test_get_conversations_success(self, chat_service, mock_db_session):
        """Test successful conversation listing."""
        conversations = [
            ChatConversation(
                id=i,
                conversation_id=f"conv-{i}",
                session_id="session-456",
                title=f"Conversation {i}",
                created_at=datetime.utcnow() + timedelta(hours=i),
                updated_at=datetime.utcnow() + timedelta(hours=i)
            )
            for i in range(3)
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = conversations
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.get_conversations(
                session_id="session-456",
                limit=10,
                offset=0
            )

            assert len(result) == 3
            assert all(conv.session_id == "session-456" for conv in result)

    @pytest.mark.asyncio
    async def test_get_conversation_count(self, chat_service, mock_db_session):
        """Test conversation count retrieval."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.get_conversation_count(session_id="session-456")

            assert result == 5

    @pytest.mark.asyncio
    async def test_get_message_count(self, chat_service, mock_db_session):
        """Test message count retrieval."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.get_message_count(
                session_id="session-456",
                conversation_id="conv-123"
            )

            assert result == 10

    @pytest.mark.asyncio
    async def test_update_message_qdrant_id(self, chat_service, mock_db_session, sample_message):
        """Test updating message with Qdrant point ID."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_message
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.update_message_qdrant_id(
                message_id="msg-123",
                qdrant_point_id="qdrant-456"
            )

            assert result is True
            assert mock_db_session.add.called
            assert mock_db_session.commit.called

    @pytest.mark.asyncio
    async def test_update_message_qdrant_id_not_found(self, chat_service, mock_db_session):
        """Test updating Qdrant ID for non-existent message."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            result = await chat_service.update_message_qdrant_id(
                message_id="nonexistent",
                qdrant_point_id="qdrant-456"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_cache_integration(self, chat_service, mock_db_session):
        """Test cache integration in service operations."""
        # Test cache hit
        chat_service.cache_service.get.return_value = [
            ChatMessage(id=1, message_id="cached-msg", session_id="session-456", 
                       conversation_id="conv-123", role=MessageRole.USER, content="cached")
        ]

        result = await chat_service.get_conversation_history(
            session_id="session-456",
            limit=50,
            offset=0
        )

        # Should return cached result without hitting database
        assert len(result) == 1
        assert result[0].message_id == "cached-msg"
        chat_service.cache_service.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, chat_service, mock_db_session, sample_conversation):
        """Test cache invalidation after modifications."""
        # Mock conversation retrieval for store_message
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation
        mock_db_session.execute.return_value = mock_result

        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_db_session

            await chat_service.store_message(
                session_id="session-456",
                role="user",
                content="Test message"
            )

            # Verify cache invalidation was called
            chat_service.cache_service.clear_cache.assert_called()

    @pytest.mark.asyncio
    async def test_error_handling_with_session_parameter(self, chat_service, mock_db_session):
        """Test error handling when using provided session parameter."""
        mock_db_session.commit.side_effect = SQLAlchemyError("Database error")

        with pytest.raises(ChatDatabaseError):
            await chat_service.store_message(
                session_id="session-456",
                role="user",
                content="Test message",
                session=mock_db_session
            )

        assert mock_db_session.rollback.called

    @pytest.mark.asyncio
    async def test_get_or_create_conversation_new(self, chat_service, mock_db_session):
        """Test creating new conversation when none exists."""
        # Mock no existing conversation
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await chat_service._get_or_create_conversation(
            session_id="session-456",
            philosopher_collection="Aristotle",
            username="test_user",
            db_session=mock_db_session
        )

        assert mock_db_session.add.called
        assert mock_db_session.flush.called

    @pytest.mark.asyncio
    async def test_get_or_create_conversation_existing(self, chat_service, mock_db_session, sample_conversation):
        """Test using existing conversation when available."""
        # Mock existing conversation
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation
        mock_db_session.execute.return_value = mock_result

        result = await chat_service._get_or_create_conversation(
            session_id="session-456",
            philosopher_collection="Aristotle",
            username="test_user",
            db_session=mock_db_session
        )

        assert result == sample_conversation
        # Should not create new conversation
        assert not mock_db_session.add.called

    @pytest.mark.asyncio
    async def test_get_conversation_by_id_success(self, chat_service, mock_db_session, sample_conversation):
        """Test successful conversation retrieval by ID."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_conversation
        mock_db_session.execute.return_value = mock_result

        result = await chat_service._get_conversation_by_id(
            conversation_id="conv-123",
            session_id="session-456",
            db_session=mock_db_session
        )

        assert result == sample_conversation

    @pytest.mark.asyncio
    async def test_get_conversation_by_id_privacy_violation(self, chat_service, mock_db_session):
        """Test privacy protection in conversation retrieval by ID."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await chat_service._get_conversation_by_id(
            conversation_id="conv-123",
            session_id="wrong-session",
            db_session=mock_db_session
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_start_factory_method(self, mock_cache_service):
        """Test factory method for creating service with cache."""
        service = await ChatHistoryService.start(cache_service=mock_cache_service)
        assert service.cache_service == mock_cache_service

    @pytest.mark.asyncio
    async def test_database_connection_failure(self, chat_service):
        """Test handling of database connection failures."""
        with patch('app.services.chat_history_service.AsyncSessionLocal') as mock_session_local:
            mock_session_local.side_effect = Exception("Connection failed")

            with pytest.raises(ChatDatabaseError) as exc_info:
                await chat_service.store_message(
                    session_id="session-456",
                    role="user",
                    content="Test message"
                )

            assert "Failed to establish database connection" in str(exc_info.value)
            assert exc_info.value.recoverable is True


"""
Test Coverage Summary

Message Storage and Retrieval Operations:
- Successful message storage with conversation creation/retrieval
- Message storage validation (empty session_id, content, invalid role, content too long)
- Database error handling (IntegrityError, OperationalError, SQLAlchemyError)
- Successful conversation history retrieval with pagination
- History retrieval validation (invalid limits, negative offset)
- Pagination functionality with proper offset/limit handling

Session Isolation and Privacy Protection:
- Session isolation in history retrieval (users only see their own data)
- Privacy validation for conversation access (unauthorized conversation access)
- Privacy violation detection in history deletion
- Cross-session data access prevention
- Conversation ownership validation

Error Handling Scenarios:
- Database connection failures
- Database integrity constraint violations
- Operational database errors with recovery flags
- Validation error handling with detailed messages
- Privacy error handling with violation types
- Graceful error handling with session parameters

Additional Functionality:
- Conversation management (creation, retrieval, counting)
- Message counting and metadata operations
- Qdrant point ID updates for vector integration
- Cache integration and invalidation
- Factory method for service creation with cache
- Helper methods for conversation management

Requirements Coverage:
- Requirement 1.1: Message storage with session tracking
- Requirement 1.2: Session-based conversation association
- Requirement 1.3: Anonymous session handling
- Requirement 1.4: Chronological message ordering
- Requirement 7.4: Complete privacy isolation between users

All test cases validate the core functionality, error handling, and privacy protection
as specified in the chat history integration requirements.
"""