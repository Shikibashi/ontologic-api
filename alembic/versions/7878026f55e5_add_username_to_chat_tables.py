"""add_username_to_chat_tables

Revision ID: 7878026f55e5
Revises: optimize_chat_indexes
Create Date: 2025-10-01 03:33:11.955262

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7878026f55e5'
down_revision: Union[str, Sequence[str], None] = 'optimize_chat_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add username fields and indexes while keeping existing indexes."""
    # Add username columns to tables
    op.add_column('chat_conversations', sa.Column('username', sa.String(), nullable=True))
    op.add_column('chat_messages', sa.Column('username', sa.String(), nullable=True))

    # Add NEW username indexes (keep existing indexes - they're still useful!)
    op.create_index(op.f('ix_chat_conversations_username'), 'chat_conversations', ['username'], unique=False)
    op.create_index('ix_chat_conversations_username_created', 'chat_conversations', ['username', 'created_at'], unique=False)
    op.create_index(op.f('ix_chat_messages_username'), 'chat_messages', ['username'], unique=False)
    op.create_index('ix_chat_messages_username_created', 'chat_messages', ['username', 'created_at'], unique=False)

    # NOTE: Existing indexes are preserved:
    # - ix_chat_conversations_session_updated_desc (session queries with ordering)
    # - ix_chat_messages_conversation_count (conversation-based queries)
    # - ix_chat_messages_qdrant_point_id (vector store lookups)
    # - ix_chat_messages_session_philosopher (philosopher collection filtering)
    # - ix_chat_messages_session_role (role-based message filtering)


def downgrade() -> None:
    """Downgrade schema - remove username fields and indexes."""
    # Drop username indexes
    op.drop_index('ix_chat_messages_username_created', table_name='chat_messages')
    op.drop_index(op.f('ix_chat_messages_username'), table_name='chat_messages')
    op.drop_index('ix_chat_conversations_username_created', table_name='chat_conversations')
    op.drop_index(op.f('ix_chat_conversations_username'), table_name='chat_conversations')

    # Drop username columns
    op.drop_column('chat_messages', 'username')
    op.drop_column('chat_conversations', 'username')

    # NOTE: We don't recreate the old indexes because they were never dropped in upgrade()
    # The existing indexes remain intact throughout the migration
