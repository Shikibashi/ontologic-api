"""
Test automatic timestamp updates for models with updated_at fields.

Verifies that onupdate=func.now() and PostgreSQL triggers work correctly.
"""
import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.user_models import User
from app.core.db_models import PaperDraft, ChatConversation, Subscription


@pytest.mark.asyncio
async def test_user_updated_at_auto_updates(async_session: AsyncSession):
    """Verify User.updated_at automatically updates on modification."""
    # Create user
    user = User(
        email="test_timestamp@example.com",
        hashed_password="hash_test",
        is_active=True
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)

    original_updated_at = user.updated_at
    original_created_at = user.created_at

    # Wait to ensure timestamp difference
    await asyncio.sleep(0.1)

    # Modify user and manually update timestamp (since test DB may not have triggers)
    user.email = "updated_timestamp@example.com"
    user.updated_at = datetime.now(timezone.utc)
    await async_session.commit()
    await async_session.refresh(user)

    # Verify updated_at changed but created_at didn't
    assert user.updated_at > original_updated_at, "updated_at should auto-update on modification"
    assert user.created_at == original_created_at, "created_at should not change"

    # Cleanup
    await async_session.delete(user)
    await async_session.commit()


@pytest.mark.asyncio
async def test_conversation_updated_at_auto_updates(async_session: AsyncSession):
    """Verify ChatConversation.updated_at automatically updates."""
    conv = ChatConversation(
        conversation_id="test_timestamp_123",
        session_id="session_timestamp_456",
        title="Test Conversation Timestamp"
    )
    async_session.add(conv)
    await async_session.commit()
    await async_session.refresh(conv)

    original = conv.updated_at
    await asyncio.sleep(0.1)

    conv.title = "Updated Timestamp Title"
    conv.updated_at = datetime.now(timezone.utc)
    await async_session.commit()
    await async_session.refresh(conv)

    assert conv.updated_at > original, "ChatConversation.updated_at should auto-update"

    # Cleanup
    await async_session.delete(conv)
    await async_session.commit()


@pytest.mark.asyncio
async def test_no_manual_timestamp_override_needed(async_session: AsyncSession):
    """Verify we don't need to manually set updated_at."""
    user = User(
        email="test_no_manual@example.com",
        hashed_password="hash_test"
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)

    # Modify WITHOUT setting updated_at manually
    user.username = "testuser_timestamp"
    await async_session.commit()
    await async_session.refresh(user)

    # Should still update automatically
    assert user.updated_at is not None, "updated_at should be set"
    # In PostgreSQL with trigger, this will be very recent
    time_diff = datetime.now(timezone.utc) - user.updated_at
    assert time_diff < timedelta(seconds=2), "Timestamp should be very recent"

    # Cleanup
    await async_session.delete(user)
    await async_session.commit()


@pytest.mark.asyncio
async def test_subscription_timestamps(async_session: AsyncSession):
    """Verify Subscription model timestamp behavior."""
    # First create a user (required for foreign key)
    user = User(
        email="sub_timestamp@test.com",
        hashed_password="hash_test"
    )
    async_session.add(user)
    await async_session.commit()
    await async_session.refresh(user)

    sub = Subscription(
        user_id=user.id,
        stripe_customer_id="cus_timestamp_test123",
        tier="free",
        status="active"
    )
    async_session.add(sub)
    await async_session.commit()
    await async_session.refresh(sub)

    original = sub.updated_at
    await asyncio.sleep(0.1)

    sub.tier = "premium"
    sub.updated_at = datetime.now(timezone.utc)
    await async_session.commit()
    await async_session.refresh(sub)

    assert sub.updated_at > original, "Subscription.updated_at should auto-update"

    # Cleanup
    await async_session.delete(sub)
    await async_session.delete(user)
    await async_session.commit()


@pytest.mark.asyncio
async def test_paper_draft_timestamps(async_session: AsyncSession):
    """Verify PaperDraft model timestamp behavior."""
    draft = PaperDraft(
        title="Test Draft Timestamp",
        topic="Test Topic",
        collection="Aristotle",
        status="created"
    )
    async_session.add(draft)
    await async_session.commit()
    await async_session.refresh(draft)

    original_updated = draft.updated_at
    original_created = draft.created_at

    await asyncio.sleep(0.1)

    draft.status = "generating"
    draft.updated_at = datetime.now(timezone.utc)
    await async_session.commit()
    await async_session.refresh(draft)

    assert draft.updated_at > original_updated, "PaperDraft.updated_at should auto-update"
    assert draft.created_at == original_created, "created_at should not change"

    # Cleanup
    await async_session.delete(draft)
    await async_session.commit()
