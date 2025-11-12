"""
Chat cleanup service for managing expired chat history data.

Handles periodic cleanup of old chat conversations and sessions based on
configured retention policies using the comprehensive ChatCleanupUtility.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from app.core.logger import log
from app.utils.chat_cleanup import ChatCleanupUtility, RetentionPolicy


class ChatCleanupService:
    """Service for cleaning up expired chat history data."""

    def __init__(self, chat_config: Any, feature_flags: Any):
        """
        Initialize cleanup service.

        Args:
            chat_config: Chat history configuration
            feature_flags: Feature flag service
        """
        self.chat_config = chat_config
        self.feature_flags = feature_flags
        self.retention_days = getattr(chat_config, 'retention_days', 30)
        
        # Create retention policy from config
        self.retention_policy = RetentionPolicy(
            max_age_days=self.retention_days,
            max_messages_per_session=getattr(chat_config, 'max_messages_per_session', 10000),
            max_conversations_per_session=getattr(chat_config, 'max_conversations_per_session', 1000),
            cleanup_batch_size=getattr(chat_config, 'cleanup_batch_size', 1000),
            orphaned_data_cleanup=getattr(chat_config, 'cleanup_orphaned_data', True),
            qdrant_cleanup=getattr(chat_config, 'cleanup_qdrant_vectors', True)
        )
        
        # Initialize cleanup utility (Qdrant service will be injected when needed)
        self.cleanup_utility = ChatCleanupUtility(retention_policy=self.retention_policy)

    async def get_cleanup_stats(self) -> Dict[str, Any]:
        """
        Get statistics about data that would be cleaned up.

        Returns:
            Dict with counts of expired conversations and messages
        """
        try:
            log.info("Getting cleanup stats")
            
            # Use the comprehensive cleanup utility to get real statistics
            stats = await self.cleanup_utility.get_cleanup_statistics()
            
            # Convert to legacy format for API compatibility
            return {
                "expired_conversations": stats.get("expired_sessions", 0),
                "expired_messages": stats.get("orphaned_messages", 0),
                "oldest_conversation_date": None,  # Could be enhanced to find actual oldest date
                "retention_days": self.retention_days,
                "cutoff_date": (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat(),
                "detailed_stats": stats  # Include full stats for debugging
            }

        except Exception as e:
            log.error(f"Error getting cleanup stats: {e}")
            return {
                "error": str(e),
                "expired_conversations": 0,
                "expired_messages": 0,
                "retention_days": self.retention_days,
                "cutoff_date": (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
            }

    async def cleanup_expired_sessions(self) -> Dict[str, Any]:
        """
        Clean up expired chat sessions and their associated data.

        Returns:
            Dict with cleanup results
        """
        try:
            log.info(f"Running cleanup for sessions older than {self.retention_days} days")

            # Get Qdrant service if available for vector cleanup
            qdrant_service = await self._get_qdrant_service()
            if qdrant_service:
                self.cleanup_utility.qdrant_service = qdrant_service

            # Perform actual cleanup using the utility
            result = await self.cleanup_utility.cleanup_expired_sessions()
            
            # Convert result to legacy format for API compatibility
            return {
                "success": len(result.errors) == 0,
                "deleted_conversations": result.conversations_deleted,
                "deleted_messages": result.messages_deleted,
                "deleted_vector_points": result.qdrant_points_deleted,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": result.duration_seconds,
                "cleanup_id": result.cleanup_id,
                "errors": result.errors
            }

        except Exception as e:
            log.error(f"Error during cleanup: {e}")
            return {
                "success": False,
                "error": str(e),
                "deleted_conversations": 0,
                "deleted_messages": 0,
                "deleted_vector_points": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def cleanup_session_data(self, session_id: str) -> Dict[str, Any]:
        """
        Delete all data for a specific session.

        Args:
            session_id: Session ID to clean up

        Returns:
            Dict with cleanup results
        """
        try:
            log.info(f"Cleaning up data for session: {session_id}")

            # Get Qdrant service if available for vector cleanup
            qdrant_service = await self._get_qdrant_service()
            if qdrant_service:
                self.cleanup_utility.qdrant_service = qdrant_service

            # Perform session-specific cleanup
            result = await self.cleanup_utility.cleanup_expired_sessions(
                session_ids=[session_id]
            )
            
            # Convert result to legacy format for API compatibility
            return {
                "success": len(result.errors) == 0,
                "session_id": session_id,
                "deleted_conversations": result.conversations_deleted,
                "deleted_messages": result.messages_deleted,
                "deleted_vector_points": result.qdrant_points_deleted,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": result.duration_seconds,
                "cleanup_id": result.cleanup_id,
                "errors": result.errors
            }

        except Exception as e:
            log.error(f"Error cleaning up session {session_id}: {e}")
            return {
                "success": False,
                "session_id": session_id,
                "error": str(e),
                "deleted_conversations": 0,
                "deleted_messages": 0,
                "deleted_vector_points": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def cleanup_orphaned_data(self) -> Dict[str, Any]:
        """
        Clean up orphaned data (messages without conversations, etc.).
        
        Returns:
            Dict with cleanup results
        """
        try:
            log.info("Running orphaned data cleanup")

            # Get Qdrant service if available for vector cleanup
            qdrant_service = await self._get_qdrant_service()
            if qdrant_service:
                self.cleanup_utility.qdrant_service = qdrant_service

            # Perform orphaned data cleanup
            result = await self.cleanup_utility.cleanup_orphaned_data()
            
            return {
                "success": len(result.errors) == 0,
                "deleted_conversations": result.conversations_deleted,
                "deleted_messages": result.messages_deleted,
                "deleted_vector_points": result.qdrant_points_deleted,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": result.duration_seconds,
                "cleanup_id": result.cleanup_id,
                "errors": result.errors
            }

        except Exception as e:
            log.error(f"Error during orphaned data cleanup: {e}")
            return {
                "success": False,
                "error": str(e),
                "deleted_conversations": 0,
                "deleted_messages": 0,
                "deleted_vector_points": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def cleanup_oversized_sessions(self) -> Dict[str, Any]:
        """
        Clean up sessions that exceed size limits.
        
        Returns:
            Dict with cleanup results
        """
        try:
            log.info("Running oversized sessions cleanup")

            # Get Qdrant service if available for vector cleanup
            qdrant_service = await self._get_qdrant_service()
            if qdrant_service:
                self.cleanup_utility.qdrant_service = qdrant_service

            # Perform oversized sessions cleanup
            result = await self.cleanup_utility.cleanup_oversized_sessions()
            
            return {
                "success": len(result.errors) == 0,
                "deleted_conversations": result.conversations_deleted,
                "deleted_messages": result.messages_deleted,
                "deleted_vector_points": result.qdrant_points_deleted,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": result.duration_seconds,
                "cleanup_id": result.cleanup_id,
                "errors": result.errors
            }

        except Exception as e:
            log.error(f"Error during oversized sessions cleanup: {e}")
            return {
                "success": False,
                "error": str(e),
                "deleted_conversations": 0,
                "deleted_messages": 0,
                "deleted_vector_points": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

    async def _get_qdrant_service(self) -> Optional[Any]:
        """
        Get ChatQdrantService instance if available.
        
        Returns:
            ChatQdrantService instance or None if not available
        """
        try:
            # Try to get Qdrant service from dependencies
            from app.core.dependencies import get_qdrant_manager
            from app.services.chat_qdrant_service import ChatQdrantService
            from app.services.llm_manager import LLMManager
            
            qdrant_manager = get_qdrant_manager()
            llm_manager = LLMManager()
            
            # Create ChatQdrantService with proper dependencies
            chat_qdrant_service = ChatQdrantService(
                qdrant_client=qdrant_manager.qclient,
                llm_manager=llm_manager
            )
            
            return chat_qdrant_service
            
        except Exception as e:
            log.warning(f"Could not initialize Qdrant service for cleanup: {e}")
            return None
