"""Optimize chat database indexes for performance

Revision ID: optimize_chat_indexes
Revises: 2a60609c7df4
Create Date: 2025-10-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'optimize_chat_indexes'
down_revision: Union[str, Sequence[str], None] = '2a60609c7df4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance optimization indexes for chat queries."""
    
    # Add composite index for pagination queries on conversations
    # This optimizes: ORDER BY updated_at DESC with session_id filtering
    op.create_index(
        'ix_chat_conversations_session_updated_desc',
        'chat_conversations',
        ['session_id', sa.text('updated_at DESC')],
        unique=False
    )
    
    # Add composite index for message search by philosopher collection
    # This optimizes: WHERE session_id = ? AND philosopher_collection = ?
    op.create_index(
        'ix_chat_messages_session_philosopher',
        'chat_messages',
        ['session_id', 'philosopher_collection'],
        unique=False
    )
    
    # Add composite index for message role filtering
    # This optimizes: WHERE session_id = ? AND role = ?
    op.create_index(
        'ix_chat_messages_session_role',
        'chat_messages',
        ['session_id', 'role'],
        unique=False
    )
    
    # Add index for Qdrant point ID lookups
    # This optimizes: WHERE qdrant_point_id = ?
    op.create_index(
        'ix_chat_messages_qdrant_point_id',
        'chat_messages',
        ['qdrant_point_id'],
        unique=False
    )
    
    # Add composite index for conversation message counting
    # This optimizes: COUNT(*) WHERE conversation_id = ?
    op.create_index(
        'ix_chat_messages_conversation_count',
        'chat_messages',
        ['conversation_id', 'id'],
        unique=False
    )


def downgrade() -> None:
    """Remove performance optimization indexes."""
    
    op.drop_index('ix_chat_messages_conversation_count', table_name='chat_messages')
    op.drop_index('ix_chat_messages_qdrant_point_id', table_name='chat_messages')
    op.drop_index('ix_chat_messages_session_role', table_name='chat_messages')
    op.drop_index('ix_chat_messages_session_philosopher', table_name='chat_messages')
    op.drop_index('ix_chat_conversations_session_updated_desc', table_name='chat_conversations')