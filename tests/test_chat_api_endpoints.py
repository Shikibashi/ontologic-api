"""
API endpoint tests for chat history with username support.

Tests POST /chat/message, GET /chat/history, POST /chat/search endpoints
with username parameters and filtering.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.chat_models import ChatMessageResponse, ChatHistoryResponse, ChatSearchResponse
from app.core.db_models import ChatMessage, ChatConversation, MessageRole


def get_mock_service(test_client, service_func):
    """Helper to get mock service from dependency overrides."""
    mock_service = test_client.app.dependency_overrides[service_func]
    if callable(mock_service):
        return mock_service()
    return mock_service


class TestChatMessageEndpoint:
    """Test suite for POST /chat/message endpoint."""

    def test_store_message_with_username(self, test_client):
        """Test storing a message with username."""
        # Mock stored message
        stored_message = ChatMessage(
            id=1,
            message_id="msg_123",
            conversation_id="conv_456",
            session_id="session_789",
            username="alice@example.com",
            role=MessageRole.USER,
            content="What is virtue ethics?",
            created_at=datetime.utcnow()
        )
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_history_service = get_mock_service(test_client, deps.get_chat_history_service)
        mock_chat_qdrant_service = get_mock_service(test_client, deps.get_chat_qdrant_service)
        
        mock_chat_history_service.store_message.return_value = stored_message
        mock_chat_qdrant_service.upload_message_to_qdrant.return_value = ["point_123"]

        # Mock chat history enabled check
        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.post(
                "/chat/message",
                json={
                    "session_id": "session_789",
                    "role": "user",
                    "content": "What is virtue ethics?",
                    "username": "alice@example.com"
                }
            )

        assert response.status_code == 201
        data = response.json()
        assert data['message_id'] == "msg_123"
        assert data['username'] == "alice@example.com"
        assert data['session_id'] == "session_789"
        assert data['content'] == "What is virtue ethics?"

    def test_store_message_without_username(self, test_client):
        """Test storing a message without username (backward compatibility)."""
        # Mock stored message
        stored_message = ChatMessage(
            id=1,
            message_id="msg_456",
            conversation_id="conv_789",
            session_id="session_012",
            username=None,
            role=MessageRole.ASSISTANT,
            content="Virtue ethics is...",
            created_at=datetime.utcnow()
        )
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_history_service = get_mock_service(test_client, deps.get_chat_history_service)
        mock_chat_qdrant_service = get_mock_service(test_client, deps.get_chat_qdrant_service)
        
        mock_chat_history_service.store_message.return_value = stored_message
        mock_chat_qdrant_service.upload_message_to_qdrant.return_value = ["point_456"]

        # Mock chat history enabled check
        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.post(
                "/chat/message",
                json={
                    "session_id": "session_012",
                    "role": "assistant",
                    "content": "Virtue ethics is..."
                }
            )

        assert response.status_code == 201
        data = response.json()
        assert data['message_id'] == "msg_456"
        assert data['username'] is None
        assert data['session_id'] == "session_012"

    def test_store_message_invalid_session_id(self, test_client):
        """Test storing a message with invalid session ID."""
        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.post(
                "/chat/message",
                json={
                    "session_id": "",
                    "role": "user",
                    "content": "Test"
                }
            )

        assert response.status_code == 400
        response_data = response.json()
        # Check if the error message is in the nested details array
        detail_obj = response_data.get('detail', {})
        details = detail_obj.get('details', [])
        assert any("Session ID cannot be empty" in detail.get('message', '') for detail in details)


class TestChatHistoryEndpoint:
    """Test suite for GET /chat/history/{session_id} endpoint."""

    def test_get_history_with_username_filter(self, test_client):
        """Test getting chat history with username filter."""
        # Mock messages
        messages = [
            ChatMessage(
                id=1,
                message_id="msg_1",
                conversation_id="conv_123",
                session_id="session_456",
                username="bob@example.com",
                role=MessageRole.USER,
                content="Question 1",
                created_at=datetime.utcnow()
            ),
            ChatMessage(
                id=2,
                message_id="msg_2",
                conversation_id="conv_123",
                session_id="session_456",
                username="bob@example.com",
                role=MessageRole.ASSISTANT,
                content="Answer 1",
                created_at=datetime.utcnow()
            )
        ]
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_history_service = get_mock_service(test_client, deps.get_chat_history_service)
        
        mock_chat_history_service.get_conversation_history.return_value = messages
        mock_chat_history_service.get_message_count.return_value = 2

        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.get(
                "/chat/history/session_456",
                params={"username": "bob@example.com"}
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data['messages']) == 2
        assert data['messages'][0]['username'] == "bob@example.com"
        assert data['total_count'] == 2

    def test_get_history_pagination(self, test_client):
        """Test chat history pagination."""
        # Mock messages
        messages = [
            ChatMessage(
                id=i,
                message_id=f"msg_{i}",
                conversation_id="conv_123",
                session_id="session_789",
                username="charlie@example.com",
                role=MessageRole.USER,
                content=f"Message {i}",
                created_at=datetime.utcnow()
            )
            for i in range(10)
        ]
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_history_service = get_mock_service(test_client, deps.get_chat_history_service)
        
        mock_chat_history_service.get_conversation_history.return_value = messages
        mock_chat_history_service.get_message_count.return_value = 50

        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.get(
                "/chat/history/session_789",
                params={"limit": 10, "offset": 0}
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data['messages']) == 10
        assert data['total_count'] == 50
        assert data['has_more'] is True


class TestChatSearchEndpoint:
    """Test suite for POST /chat/search endpoint."""

    def test_search_with_username(self, test_client):
        """Test searching chat history with username."""
        # Mock search results
        search_results = [
            {
                "message_id": "msg_123",
                "conversation_id": "conv_456",
                "session_id": "session_789",
                "username": "diane@example.com",
                "role": "user",
                "content": "What is ethics?",
                "philosopher_collection": "Aristotle",
                "created_at": datetime.utcnow().isoformat(),
                "relevance_score": 0.95
            }
        ]
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_qdrant_service = test_client.app.dependency_overrides[deps.get_chat_qdrant_service]()
        
        mock_chat_qdrant_service.search_messages.return_value = search_results

        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.post(
                "/chat/search",
                json={
                    "session_id": "session_789",
                    "query": "ethics",
                    "username": "diane@example.com",
                    "include_pdf_context": False
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert data['total_found'] == 1
        assert data['results'][0]['username'] == "diane@example.com"
        assert data['results'][0]['relevance_score'] == 0.95

    def test_search_without_username(self, test_client):
        """Test searching without username (backward compatibility)."""
        # Mock search results
        search_results = [
            {
                "message_id": "msg_456",
                "conversation_id": "conv_789",
                "session_id": "session_012",
                "username": None,
                "role": "assistant",
                "content": "Ethics is the study of...",
                "created_at": datetime.utcnow().isoformat(),
                "relevance_score": 0.85
            }
        ]
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_qdrant_service = test_client.app.dependency_overrides[deps.get_chat_qdrant_service]()
        
        mock_chat_qdrant_service.search_messages.return_value = search_results

        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.post(
                "/chat/search",
                json={
                    "session_id": "session_012",
                    "query": "ethics"
                }
            )

        assert response.status_code == 200
        data = response.json()
        assert data['results'][0]['username'] is None

    def test_search_empty_query(self, test_client):
        """Test searching with empty query."""
        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.post(
                "/chat/search",
                json={
                    "session_id": "session_123",
                    "query": ""
                }
            )

        assert response.status_code == 422  # Validation error


class TestChatConversationsEndpoint:
    """Test suite for GET /chat/conversations/{session_id} endpoint."""

    def test_get_conversations_with_username(self, test_client):
        """Test getting conversations with username."""
        # Mock conversations
        conversations = [
            ChatConversation(
                id=1,
                conversation_id="conv_123",
                session_id="session_456",
                username="eve@example.com",
                title="Ethics Discussion",
                philosopher_collection="Aristotle",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
        ]
        
        # Configure the mock that's already set up in conftest.py
        from app.core import dependencies as deps
        mock_chat_history_service = test_client.app.dependency_overrides[deps.get_chat_history_service]()
        
        mock_chat_history_service.get_conversations.return_value = conversations
        mock_chat_history_service.get_conversation_count.return_value = 1
        mock_chat_history_service.get_message_count.return_value = 5

        with patch('app.router.chat_history.is_chat_history_enabled', return_value=True):
            response = test_client.get("/chat/conversations/session_456")

        assert response.status_code == 200
        data = response.json()
        assert len(data['conversations']) == 1
        assert data['conversations'][0]['username'] == "eve@example.com"
        assert data['conversations'][0]['message_count'] == 5
