"""
Chat history cleanup utilities for data maintenance and retention.

Provides utilities for cleaning up expired sessions, old data,
and maintaining database health with configurable retention policies.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from sqlmodel import select, and_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_models import ChatMessage, ChatConversation
from app.core.database import AsyncSessionLocal
from app.core.logger import log
from app.services.chat_qdrant_service import ChatQdrantService


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""
    operation: str
    conversations_deleted: int
    messages_deleted: int
    qdrant_points_deleted: int
    errors: List[str]
    duration_seconds: float
    cleanup_id: str


@dataclass
class RetentionPolicy:
    """Configuration for data retention policies."""
    max_age_days: int = 90  # Default 90 days retention
    max_messages_per_session: int = 10000  # Max messages per session
    max_conversations_per_session: int = 1000  # Max conversations per session
    cleanup_batch_size: int = 1000  # Batch size for cleanup operations
    orphaned_data_cleanup: bool = True  # Clean up orphaned data
    qdrant_cleanup: bool = True  # Clean up corresponding Qdrant data


class ChatCleanupUtility:
    """
    Utility for cleaning up chat history data with configurable retention policies.
    
    Handles expired sessions, old conversations, orphaned data, and maintains
    database health while preserving data integrity.
    """
    
    def __init__(
        self,
        retention_policy: Optional[RetentionPolicy] = None,
        qdrant_service: Optional[ChatQdrantService] = None
    ):
        """
        Initialize cleanup utility.
        
        Args:
            retention_policy: Data retention configuration
            qdrant_service: Optional Qdrant service for vector cleanup
        """
        self.retention_policy = retention_policy or RetentionPolicy()
        self.qdrant_service = qdrant_service
    
    async def cleanup_expired_sessions(
        self,
        cutoff_date: Optional[datetime] = None,
        session_ids: Optional[List[str]] = None
    ) -> CleanupResult:
        """
        Clean up expired chat sessions based on age or specific session IDs.
        
        Args:
            cutoff_date: Optional cutoff date (defaults to retention policy)
            session_ids: Optional specific session IDs to clean up
            
        Returns:
            CleanupResult with cleanup statistics
        """
        cleanup_id = f"expired_sessions_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc)
        
        if not cutoff_date:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_policy.max_age_days)
        
        try:
            conversations_deleted = 0
            messages_deleted = 0
            qdrant_points_deleted = 0
            errors = []
            
            async with AsyncSessionLocal() as db_session:
                # Find sessions to clean up
                if session_ids:
                    # Clean up specific sessions
                    sessions_to_cleanup = session_ids
                    log.info(f"Cleaning up {len(session_ids)} specific sessions")
                else:
                    # Find expired sessions
                    sessions_to_cleanup = await self._find_expired_sessions(db_session, cutoff_date)
                    log.info(f"Found {len(sessions_to_cleanup)} expired sessions to clean up")
                
                # Process sessions in batches
                for i in range(0, len(sessions_to_cleanup), self.retention_policy.cleanup_batch_size):
                    batch = sessions_to_cleanup[i:i + self.retention_policy.cleanup_batch_size]
                    
                    try:
                        batch_result = await self._cleanup_session_batch(db_session, batch)
                        conversations_deleted += batch_result[0]
                        messages_deleted += batch_result[1]
                        qdrant_points_deleted += batch_result[2]
                        
                        log.info(f"Cleaned up batch {i//self.retention_policy.cleanup_batch_size + 1}: "
                                f"{batch_result[1]} messages, {batch_result[0]} conversations")
                        
                    except Exception as e:
                        error_msg = f"Error cleaning up batch {i//self.retention_policy.cleanup_batch_size + 1}: {e}"
                        errors.append(error_msg)
                        log.error(error_msg)
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                operation="cleanup_expired_sessions",
                conversations_deleted=conversations_deleted,
                messages_deleted=messages_deleted,
                qdrant_points_deleted=qdrant_points_deleted,
                errors=errors,
                duration_seconds=duration,
                cleanup_id=cleanup_id
            )
            
            log.info(f"Expired sessions cleanup completed: {conversations_deleted} conversations, "
                    f"{messages_deleted} messages deleted in {duration:.2f}s")
            
            return result
            
        except Exception as e:
            log.error(f"Expired sessions cleanup failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return CleanupResult(
                operation="cleanup_expired_sessions",
                conversations_deleted=0,
                messages_deleted=0,
                qdrant_points_deleted=0,
                errors=[str(e)],
                duration_seconds=duration,
                cleanup_id=cleanup_id
            )
    
    async def cleanup_oversized_sessions(self) -> CleanupResult:
        """
        Clean up sessions that exceed message or conversation limits.
        
        Returns:
            CleanupResult with cleanup statistics
        """
        cleanup_id = f"oversized_sessions_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc)
        
        try:
            conversations_deleted = 0
            messages_deleted = 0
            qdrant_points_deleted = 0
            errors = []
            
            async with AsyncSessionLocal() as db_session:
                # Find sessions with too many messages
                oversized_sessions = await self._find_oversized_sessions(db_session)
                
                log.info(f"Found {len(oversized_sessions)} oversized sessions to clean up")
                
                for session_id, message_count, conversation_count in oversized_sessions:
                    try:
                        # Clean up excess messages (keep most recent)
                        if message_count > self.retention_policy.max_messages_per_session:
                            excess_messages = message_count - self.retention_policy.max_messages_per_session
                            deleted_messages = await self._cleanup_excess_messages(
                                db_session, session_id, excess_messages
                            )
                            messages_deleted += deleted_messages
                        
                        # Clean up excess conversations (keep most recent)
                        if conversation_count > self.retention_policy.max_conversations_per_session:
                            excess_conversations = conversation_count - self.retention_policy.max_conversations_per_session
                            deleted_conversations = await self._cleanup_excess_conversations(
                                db_session, session_id, excess_conversations
                            )
                            conversations_deleted += deleted_conversations
                        
                    except Exception as e:
                        error_msg = f"Error cleaning up oversized session {session_id}: {e}"
                        errors.append(error_msg)
                        log.error(error_msg)
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                operation="cleanup_oversized_sessions",
                conversations_deleted=conversations_deleted,
                messages_deleted=messages_deleted,
                qdrant_points_deleted=qdrant_points_deleted,
                errors=errors,
                duration_seconds=duration,
                cleanup_id=cleanup_id
            )
            
            log.info(f"Oversized sessions cleanup completed: {conversations_deleted} conversations, "
                    f"{messages_deleted} messages deleted in {duration:.2f}s")
            
            return result
            
        except Exception as e:
            log.error(f"Oversized sessions cleanup failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return CleanupResult(
                operation="cleanup_oversized_sessions",
                conversations_deleted=0,
                messages_deleted=0,
                qdrant_points_deleted=0,
                errors=[str(e)],
                duration_seconds=duration,
                cleanup_id=cleanup_id
            )
    
    async def cleanup_orphaned_data(self) -> CleanupResult:
        """
        Clean up orphaned data (messages without conversations, etc.).
        
        Returns:
            CleanupResult with cleanup statistics
        """
        cleanup_id = f"orphaned_data_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        start_time = datetime.now(timezone.utc)
        
        try:
            conversations_deleted = 0
            messages_deleted = 0
            qdrant_points_deleted = 0
            errors = []
            
            async with AsyncSessionLocal() as db_session:
                # Find orphaned messages (messages without valid conversations)
                orphaned_messages = await self._find_orphaned_messages(db_session)
                
                if orphaned_messages:
                    log.info(f"Found {len(orphaned_messages)} orphaned messages")
                    
                    # Collect Qdrant point IDs for cleanup
                    qdrant_point_ids = [
                        msg.qdrant_point_id for msg in orphaned_messages 
                        if msg.qdrant_point_id
                    ]
                    
                    # Delete orphaned messages in bulk
                    message_ids = [message.id for message in orphaned_messages]
                    if message_ids:
                        delete_stmt = delete(ChatMessage).where(ChatMessage.id.in_(message_ids))
                        result = await db_session.execute(delete_stmt)
                        deleted_count = result.rowcount
                        if deleted_count is None or deleted_count < 0:
                            deleted_count = len(message_ids)
                        messages_deleted += deleted_count
                        await db_session.commit()
                    
                    # Clean up corresponding Qdrant points
                    if self.qdrant_service and qdrant_point_ids:
                        try:
                            deleted_points = await self._cleanup_qdrant_points(qdrant_point_ids)
                            qdrant_points_deleted += deleted_points
                        except Exception as e:
                            errors.append(f"Qdrant cleanup error: {e}")
                
                # Find empty conversations (conversations without messages)
                empty_conversations = await self._find_empty_conversations(db_session)
                
                if empty_conversations:
                    log.info(f"Found {len(empty_conversations)} empty conversations")
                    
                    conversation_ids = [conversation.id for conversation in empty_conversations]
                    if conversation_ids:
                        delete_stmt = delete(ChatConversation).where(ChatConversation.id.in_(conversation_ids))
                        result = await db_session.execute(delete_stmt)
                        deleted_count = result.rowcount
                        if deleted_count is None or deleted_count < 0:
                            deleted_count = len(conversation_ids)
                        conversations_deleted += deleted_count
                        await db_session.commit()
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            
            result = CleanupResult(
                operation="cleanup_orphaned_data",
                conversations_deleted=conversations_deleted,
                messages_deleted=messages_deleted,
                qdrant_points_deleted=qdrant_points_deleted,
                errors=errors,
                duration_seconds=duration,
                cleanup_id=cleanup_id
            )
            
            log.info(f"Orphaned data cleanup completed: {conversations_deleted} conversations, "
                    f"{messages_deleted} messages, {qdrant_points_deleted} Qdrant points deleted")
            
            return result
            
        except Exception as e:
            log.error(f"Orphaned data cleanup failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return CleanupResult(
                operation="cleanup_orphaned_data",
                conversations_deleted=0,
                messages_deleted=0,
                qdrant_points_deleted=0,
                errors=[str(e)],
                duration_seconds=duration,
                cleanup_id=cleanup_id
            )
    
    async def get_cleanup_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about data that could be cleaned up.
        
        Returns:
            Dictionary with cleanup statistics and recommendations
        """
        try:
            async with AsyncSessionLocal() as db_session:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_policy.max_age_days)
                
                # Count expired sessions
                expired_sessions = await self._find_expired_sessions(db_session, cutoff_date)
                
                # Count oversized sessions
                oversized_sessions = await self._find_oversized_sessions(db_session)
                
                # Count orphaned data
                orphaned_messages = await self._find_orphaned_messages(db_session)
                empty_conversations = await self._find_empty_conversations(db_session)
                
                # Total counts
                total_conversations_stmt = select(func.count(ChatConversation.id))
                total_messages_stmt = select(func.count(ChatMessage.id))
                
                total_conversations = (await db_session.execute(total_conversations_stmt)).scalar() or 0
                total_messages = (await db_session.execute(total_messages_stmt)).scalar() or 0
                
                return {
                    "total_conversations": total_conversations,
                    "total_messages": total_messages,
                    "expired_sessions": len(expired_sessions),
                    "oversized_sessions": len(oversized_sessions),
                    "orphaned_messages": len(orphaned_messages),
                    "empty_conversations": len(empty_conversations),
                    "retention_policy": {
                        "max_age_days": self.retention_policy.max_age_days,
                        "max_messages_per_session": self.retention_policy.max_messages_per_session,
                        "max_conversations_per_session": self.retention_policy.max_conversations_per_session
                    },
                    "recommendations": self._generate_cleanup_recommendations(
                        len(expired_sessions), len(oversized_sessions), 
                        len(orphaned_messages), len(empty_conversations)
                    )
                }
                
        except Exception as e:
            log.error(f"Failed to get cleanup statistics: {e}")
            return {"error": str(e)}
    
    async def _find_expired_sessions(
        self, 
        db_session: AsyncSession, 
        cutoff_date: datetime
    ) -> List[str]:
        """Find sessions older than cutoff date."""
        statement = (
            select(ChatConversation.session_id)
            .where(ChatConversation.updated_at < cutoff_date)
            .distinct()
        )
        result = await db_session.execute(statement)
        return [row[0] for row in result.fetchall()]
    
    async def _find_oversized_sessions(self, db_session: AsyncSession) -> List[Tuple[str, int, int]]:
        """Find sessions that exceed size limits."""
        # Get message counts per session
        message_counts_stmt = (
            select(
                ChatMessage.session_id,
                func.count(ChatMessage.id).label('message_count')
            )
            .group_by(ChatMessage.session_id)
            .having(func.count(ChatMessage.id) > self.retention_policy.max_messages_per_session)
        )
        
        # Get conversation counts per session
        conversation_counts_stmt = (
            select(
                ChatConversation.session_id,
                func.count(ChatConversation.id).label('conversation_count')
            )
            .group_by(ChatConversation.session_id)
            .having(func.count(ChatConversation.id) > self.retention_policy.max_conversations_per_session)
        )
        
        message_results = await db_session.execute(message_counts_stmt)
        conversation_results = await db_session.execute(conversation_counts_stmt)
        
        # Combine results
        oversized_sessions = {}
        
        for session_id, count in message_results.fetchall():
            oversized_sessions[session_id] = [count, 0]
        
        for session_id, count in conversation_results.fetchall():
            if session_id in oversized_sessions:
                oversized_sessions[session_id][1] = count
            else:
                oversized_sessions[session_id] = [0, count]
        
        return [(session_id, msg_count, conv_count) 
                for session_id, (msg_count, conv_count) in oversized_sessions.items()]
    
    async def _find_orphaned_messages(self, db_session: AsyncSession) -> List[ChatMessage]:
        """Find messages without valid conversations."""
        statement = (
            select(ChatMessage)
            .outerjoin(ChatConversation, ChatMessage.conversation_id == ChatConversation.conversation_id)
            .where(ChatConversation.conversation_id.is_(None))
        )
        result = await db_session.execute(statement)
        return result.scalars().all()
    
    async def _find_empty_conversations(self, db_session: AsyncSession) -> List[ChatConversation]:
        """Find conversations without any messages."""
        statement = (
            select(ChatConversation)
            .outerjoin(ChatMessage, ChatConversation.conversation_id == ChatMessage.conversation_id)
            .where(ChatMessage.conversation_id.is_(None))
        )
        result = await db_session.execute(statement)
        return result.scalars().all()
    
    async def _cleanup_session_batch(
        self, 
        db_session: AsyncSession, 
        session_ids: List[str]
    ) -> Tuple[int, int, int]:
        """Clean up a batch of sessions."""
        conversations_deleted = 0
        messages_deleted = 0
        qdrant_points_deleted = 0
        
        for session_id in session_ids:
            # Get Qdrant point IDs for cleanup
            qdrant_point_ids = []
            if self.retention_policy.qdrant_cleanup:
                messages_stmt = select(ChatMessage.qdrant_point_id).where(
                    and_(
                        ChatMessage.session_id == session_id,
                        ChatMessage.qdrant_point_id.is_not(None)
                    )
                )
                result = await db_session.execute(messages_stmt)
                qdrant_point_ids = [row[0] for row in result.fetchall()]
            
            # Delete messages
            messages_stmt = delete(ChatMessage).where(ChatMessage.session_id == session_id)
            messages_result = await db_session.execute(messages_stmt)
            messages_deleted += messages_result.rowcount
            
            # Delete conversations
            conversations_stmt = delete(ChatConversation).where(ChatConversation.session_id == session_id)
            conversations_result = await db_session.execute(conversations_stmt)
            conversations_deleted += conversations_result.rowcount
            
            # Clean up Qdrant points
            if self.qdrant_service and qdrant_point_ids:
                try:
                    deleted_points = await self._cleanup_qdrant_points(qdrant_point_ids)
                    qdrant_points_deleted += deleted_points
                except Exception as e:
                    log.warning(f"Failed to cleanup Qdrant points for session {session_id}: {e}")
        
        await db_session.commit()
        return conversations_deleted, messages_deleted, qdrant_points_deleted
    
    async def _cleanup_excess_messages(
        self, 
        db_session: AsyncSession, 
        session_id: str, 
        excess_count: int
    ) -> int:
        """Clean up excess messages, keeping the most recent ones."""
        # Get oldest messages to delete
        statement = (
            select(ChatMessage.id, ChatMessage.qdrant_point_id)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(excess_count)
        )
        result = await db_session.execute(statement)
        messages_to_delete = result.fetchall()
        
        if not messages_to_delete:
            return 0
        
        # Collect Qdrant point IDs
        qdrant_point_ids = [row[1] for row in messages_to_delete if row[1]]
        message_ids = [row[0] for row in messages_to_delete]
        
        # Delete messages
        delete_stmt = delete(ChatMessage).where(ChatMessage.id.in_(message_ids))
        result = await db_session.execute(delete_stmt)
        
        # Clean up Qdrant points
        if self.qdrant_service and qdrant_point_ids:
            try:
                await self._cleanup_qdrant_points(qdrant_point_ids)
            except Exception as e:
                log.warning(f"Failed to cleanup Qdrant points for excess messages: {e}")
        
        return result.rowcount
    
    async def _cleanup_excess_conversations(
        self, 
        db_session: AsyncSession, 
        session_id: str, 
        excess_count: int
    ) -> int:
        """Clean up excess conversations, keeping the most recent ones."""
        # Get oldest conversations to delete
        statement = (
            select(ChatConversation.conversation_id)
            .where(ChatConversation.session_id == session_id)
            .order_by(ChatConversation.updated_at.asc())
            .limit(excess_count)
        )
        result = await db_session.execute(statement)
        conversation_ids = [row[0] for row in result.fetchall()]
        
        if not conversation_ids:
            return 0
        
        # Delete associated messages first
        messages_delete_stmt = delete(ChatMessage).where(
            ChatMessage.conversation_id.in_(conversation_ids)
        )
        await db_session.execute(messages_delete_stmt)
        
        # Delete conversations
        conversations_delete_stmt = delete(ChatConversation).where(
            ChatConversation.conversation_id.in_(conversation_ids)
        )
        result = await db_session.execute(conversations_delete_stmt)
        
        return result.rowcount
    
    async def _cleanup_qdrant_points(self, point_ids: List[str]) -> int:
        """Clean up Qdrant points by IDs."""
        if not self.qdrant_service or not point_ids:
            return 0
        
        try:
            # Delete points from Qdrant
            deleted_count = await self.qdrant_service.delete_points_by_ids(point_ids)
            log.info(f"Deleted {deleted_count} points from Qdrant")
            return deleted_count
        except Exception as e:
            log.error(f"Failed to delete Qdrant points: {e}")
            return 0
    
    def _generate_cleanup_recommendations(
        self, 
        expired_sessions: int, 
        oversized_sessions: int, 
        orphaned_messages: int, 
        empty_conversations: int
    ) -> List[str]:
        """Generate cleanup recommendations based on statistics."""
        recommendations = []
        
        if expired_sessions > 0:
            recommendations.append(
                f"Consider cleaning up {expired_sessions} expired sessions "
                f"(older than {self.retention_policy.max_age_days} days)"
            )
        
        if oversized_sessions > 0:
            recommendations.append(
                f"Consider cleaning up {oversized_sessions} oversized sessions "
                f"(exceeding message/conversation limits)"
            )
        
        if orphaned_messages > 0:
            recommendations.append(
                f"Consider cleaning up {orphaned_messages} orphaned messages "
                f"(messages without valid conversations)"
            )
        
        if empty_conversations > 0:
            recommendations.append(
                f"Consider cleaning up {empty_conversations} empty conversations "
                f"(conversations without messages)"
            )
        
        if not recommendations:
            recommendations.append("No cleanup needed - data is within retention policies")
        
        return recommendations


# Convenience functions for common cleanup operations

async def cleanup_expired_chat_data(
    max_age_days: int = 90,
    qdrant_service: Optional[ChatQdrantService] = None
) -> CleanupResult:
    """
    Convenience function to clean up expired chat data.
    
    Args:
        max_age_days: Maximum age in days for data retention
        qdrant_service: Optional Qdrant service for vector cleanup
        
    Returns:
        CleanupResult with operation statistics
    """
    policy = RetentionPolicy(max_age_days=max_age_days)
    cleanup_utility = ChatCleanupUtility(retention_policy=policy, qdrant_service=qdrant_service)
    return await cleanup_utility.cleanup_expired_sessions()


async def cleanup_oversized_chat_sessions(
    max_messages: int = 10000,
    max_conversations: int = 1000,
    qdrant_service: Optional[ChatQdrantService] = None
) -> CleanupResult:
    """
    Convenience function to clean up oversized chat sessions.
    
    Args:
        max_messages: Maximum messages per session
        max_conversations: Maximum conversations per session
        qdrant_service: Optional Qdrant service for vector cleanup
        
    Returns:
        CleanupResult with operation statistics
    """
    policy = RetentionPolicy(
        max_messages_per_session=max_messages,
        max_conversations_per_session=max_conversations
    )
    cleanup_utility = ChatCleanupUtility(retention_policy=policy, qdrant_service=qdrant_service)
    return await cleanup_utility.cleanup_oversized_sessions()


async def cleanup_orphaned_chat_data(
    qdrant_service: Optional[ChatQdrantService] = None
) -> CleanupResult:
    """
    Convenience function to clean up orphaned chat data.
    
    Args:
        qdrant_service: Optional Qdrant service for vector cleanup
        
    Returns:
        CleanupResult with operation statistics
    """
    cleanup_utility = ChatCleanupUtility(qdrant_service=qdrant_service)
    return await cleanup_utility.cleanup_orphaned_data()
