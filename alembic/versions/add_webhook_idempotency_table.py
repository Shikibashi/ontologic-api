"""add webhook idempotency table

Revision ID: webhook_idempotency
Revises: ebaa477edc3e
Create Date: 2025-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'webhook_idempotency'
down_revision: Union[str, None] = 'ebaa477edc3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create webhook_events table for idempotency tracking.

    Prevents duplicate webhook processing by tracking event IDs with:
    - event_id (PRIMARY KEY): Stripe event ID (unique, prevents duplicates)
    - event_type: Type of webhook event (e.g., 'checkout.session.completed')
    - processed_at: Timestamp when event was processed
    - payload: JSONB field for storing raw event data (for debugging)

    The UNIQUE constraint on event_id ensures that INSERT ... ON CONFLICT
    can be used for atomic idempotency checks.
    """
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', name='uq_webhook_events_event_id')
    )

    # Index for querying by event_type
    op.create_index(
        'ix_webhook_events_event_type',
        'webhook_events',
        ['event_type']
    )

    # Index for querying by processed_at (for cleanup jobs)
    op.create_index(
        'ix_webhook_events_processed_at',
        'webhook_events',
        ['processed_at']
    )


def downgrade() -> None:
    """Drop webhook_events table and its indexes."""
    op.drop_index('ix_webhook_events_processed_at', table_name='webhook_events')
    op.drop_index('ix_webhook_events_event_type', table_name='webhook_events')
    op.drop_table('webhook_events')
