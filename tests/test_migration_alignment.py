"""Tests to verify Alembic migrations align with SQLModel definitions."""
import pytest
from sqlalchemy import inspect
from app.core.database import engine
from app.core.db_models import ChatConversation, ChatMessage


@pytest.mark.asyncio
async def test_chat_conversation_schema_alignment():
    """Verify chat_conversations table matches ChatConversation model."""
    async with engine.begin() as conn:
        await conn.run_sync(_check_chat_conversations_schema)


def _check_chat_conversations_schema(conn):
    """Synchronous helper to inspect chat_conversations schema."""
    inspector = inspect(conn)
    columns = {col['name']: col for col in inspector.get_columns('chat_conversations')}
    indexes = inspector.get_indexes('chat_conversations')

    # Check required columns exist
    assert 'id' in columns
    assert 'conversation_id' in columns
    assert 'session_id' in columns
    assert 'username' in columns  # Added in migration 7878026f55e5
    assert 'title' in columns
    assert 'philosopher_collection' in columns
    assert 'created_at' in columns
    assert 'updated_at' in columns

    # Check indexes exist
    index_names = [idx['name'] for idx in indexes]
    assert 'ix_chat_conversations_conversation_id' in index_names
    assert 'ix_chat_conversations_session_id' in index_names
    assert 'ix_chat_conversations_username' in index_names
    assert 'ix_chat_conversations_session_created' in index_names
    assert 'ix_chat_conversations_username_created' in index_names


@pytest.mark.asyncio
async def test_chat_message_schema_alignment():
    """Verify chat_messages table matches ChatMessage model."""
    async with engine.begin() as conn:
        await conn.run_sync(_check_chat_messages_schema)


def _check_chat_messages_schema(conn):
    """Synchronous helper to inspect chat_messages schema."""
    inspector = inspect(conn)
    columns = {col['name']: col for col in inspector.get_columns('chat_messages')}
    indexes = inspector.get_indexes('chat_messages')

    # Check required columns exist
    assert 'id' in columns
    assert 'message_id' in columns
    assert 'conversation_id' in columns
    assert 'session_id' in columns
    assert 'username' in columns  # Added in migration 7878026f55e5
    assert 'role' in columns
    assert 'content' in columns
    assert 'philosopher_collection' in columns
    assert 'qdrant_point_id' in columns
    assert 'created_at' in columns

    # Check indexes exist
    index_names = [idx['name'] for idx in indexes]
    assert 'ix_chat_messages_message_id' in index_names
    assert 'ix_chat_messages_conversation_id' in index_names
    assert 'ix_chat_messages_session_id' in index_names
    assert 'ix_chat_messages_username' in index_names
    assert 'ix_chat_messages_session_created' in index_names
    assert 'ix_chat_messages_conversation_created' in index_names
    assert 'ix_chat_messages_username_created' in index_names


@pytest.mark.asyncio
async def test_timestamp_columns_are_timezone_aware():
    """Verify timestamp columns use timezone-aware types."""
    async with engine.begin() as conn:
        await conn.run_sync(_check_timestamp_types)


def _check_timestamp_types(conn):
    """Synchronous helper to check timestamp column types."""
    inspector = inspect(conn)

    # Check chat_conversations timestamps
    conv_columns = {col['name']: col for col in inspector.get_columns('chat_conversations')}
    assert conv_columns['created_at']['type'].timezone is True
    assert conv_columns['updated_at']['type'].timezone is True

    # Check chat_messages timestamps
    msg_columns = {col['name']: col for col in inspector.get_columns('chat_messages')}
    assert msg_columns['created_at']['type'].timezone is True
