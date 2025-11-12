"""
Unit tests for database models with username support.

Tests chat conversation and message models including username fields
and proper indexing.
"""

import pytest
from datetime import datetime
from app.core.db_models import ChatConversation, ChatMessage, MessageRole


def test_chat_conversation_with_username():
    """Test ChatConversation model with username field."""
    conversation = ChatConversation(
        conversation_id="conv_123",
        session_id="session_456",
        username="alice@example.com",
        philosopher_collection="Aristotle"
    )

    assert conversation.conversation_id == "conv_123"
    assert conversation.session_id == "session_456"
    assert conversation.username == "alice@example.com"
    assert conversation.philosopher_collection == "Aristotle"
    assert conversation.title is None


def test_chat_conversation_without_username():
    """Test ChatConversation model without username (backward compatibility)."""
    conversation = ChatConversation(
        conversation_id="conv_123",
        session_id="session_456",
        philosopher_collection="Plato"
    )

    assert conversation.conversation_id == "conv_123"
    assert conversation.session_id == "session_456"
    assert conversation.username is None
    assert conversation.philosopher_collection == "Plato"


def test_chat_message_with_username():
    """Test ChatMessage model with username field."""
    message = ChatMessage(
        message_id="msg_123",
        conversation_id="conv_456",
        session_id="session_789",
        username="bob@example.com",
        role=MessageRole.USER,
        content="What is virtue ethics?"
    )

    assert message.message_id == "msg_123"
    assert message.conversation_id == "conv_456"
    assert message.session_id == "session_789"
    assert message.username == "bob@example.com"
    assert message.role == MessageRole.USER
    assert message.content == "What is virtue ethics?"


def test_chat_message_without_username():
    """Test ChatMessage model without username (backward compatibility)."""
    message = ChatMessage(
        message_id="msg_123",
        conversation_id="conv_456",
        session_id="session_789",
        role=MessageRole.ASSISTANT,
        content="Virtue ethics is a moral philosophy..."
    )

    assert message.message_id == "msg_123"
    assert message.username is None
    assert message.role == MessageRole.ASSISTANT


def test_chat_conversation_timestamps():
    """Test ChatConversation timestamp fields."""
    conversation = ChatConversation(
        conversation_id="conv_123",
        session_id="session_456"
    )

    assert conversation.created_at is not None
    assert conversation.updated_at is not None
    assert isinstance(conversation.created_at, datetime)
    assert isinstance(conversation.updated_at, datetime)


def test_chat_message_timestamps():
    """Test ChatMessage timestamp field."""
    message = ChatMessage(
        message_id="msg_123",
        conversation_id="conv_456",
        session_id="session_789",
        role=MessageRole.USER,
        content="Test message"
    )

    assert message.created_at is not None
    assert isinstance(message.created_at, datetime)


def test_message_role_enum():
    """Test MessageRole enum values."""
    assert MessageRole.USER.value == "user"
    assert MessageRole.ASSISTANT.value == "assistant"

    # Test enum creation
    user_role = MessageRole("user")
    assistant_role = MessageRole("assistant")

    assert user_role == MessageRole.USER
    assert assistant_role == MessageRole.ASSISTANT


def test_message_role_invalid():
    """Test MessageRole with invalid value."""
    with pytest.raises(ValueError):
        MessageRole("invalid_role")


def test_chat_conversation_optional_fields():
    """Test ChatConversation with all optional fields."""
    conversation = ChatConversation(
        conversation_id="conv_123",
        session_id="session_456",
        username="charlie@example.com",
        title="Discussion on Ethics",
        philosopher_collection="Kant"
    )

    assert conversation.title == "Discussion on Ethics"
    assert conversation.username == "charlie@example.com"
    assert conversation.philosopher_collection == "Kant"


def test_chat_message_optional_fields():
    """Test ChatMessage with all optional fields."""
    message = ChatMessage(
        message_id="msg_123",
        conversation_id="conv_456",
        session_id="session_789",
        username="diane@example.com",
        role=MessageRole.USER,
        content="What is categorical imperative?",
        philosopher_collection="Kant",
        qdrant_point_id="point_abc_123"
    )

    assert message.username == "diane@example.com"
    assert message.philosopher_collection == "Kant"
    assert message.qdrant_point_id == "point_abc_123"


def test_chat_conversation_relationships():
    """Test ChatConversation relationships."""
    conversation = ChatConversation(
        conversation_id="conv_123",
        session_id="session_456"
    )

    # Test that messages relationship exists and is initially empty
    assert hasattr(conversation, 'messages')
    assert conversation.messages == []
