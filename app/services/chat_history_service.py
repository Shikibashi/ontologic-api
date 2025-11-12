"""
Chat History Service for PostgreSQL operations.

Handles persistent storage and retrieval of chat conversations and messages
with proper session isolation and privacy protection. Enhanced with comprehensive
error handling and graceful degradation.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlmodel import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError

from app.core.db_models import ChatConversation, ChatMessage, MessageRole
from app.core.database import AsyncSessionLocal
from app.core.logger import log
from app.core.chat_exceptions import (
    ChatDatabaseError, ChatValidationError, ChatPrivacyError,
    ChatOperationResult
)
from app.core.chat_error_handler import database_fallback_decorator
from app.services.chat_monitoring import monitor_chat_operation, chat_monitoring
from app.services.cache_service import RedisCacheService


class ChatHistoryService:
    """
    Service layer for managing chat conversations and messages.

    Provides session-based message storage, conversation grouping,
    and retrieval with proper privacy isolation. Enhanced with caching
    for improved performance.

    LIFECYCLE: This service is lifespan-managed. It is initialized during
    application startup and stored in app.state. Access via dependency
    injection using get_chat_history_service() from app.core.dependencies.

    Do not instantiate directly in request handlers. Use:
        async def my_endpoint(chat_history: ChatHistoryServiceDep):
            # Use chat_history here
    """

    def __init__(self, cache_service: Optional[RedisCacheService] = None):
        """
        Initialize with optional cache service.

        NOTE: For lifespan-managed initialization, use the ChatHistoryService.start()
        classmethod instead of calling __init__ directly.

        Args:
            cache_service: Optional Redis cache service for performance optimization
        """
        self.cache_service = cache_service

    @classmethod
    async def start(cls, cache_service: Optional[RedisCacheService] = None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            cache_service: Optional Redis cache service for performance optimization

        Returns:
            Initialized ChatHistoryService instance
        """
        instance = cls(cache_service=cache_service)
        log.info("ChatHistoryService initialized for lifespan management")
        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        # Clean up any async resources if needed
        log.info("ChatHistoryService cleaned up")

    @monitor_chat_operation("store_message")
    async def store_message(
        self,
        session_id: str,
        role: str,
        content: str,
        philosopher_collection: Optional[str] = None,
        conversation_id: Optional[str] = None,
        username: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> ChatMessage:
        """
        Store a chat message with proper session isolation and comprehensive error handling.

        Args:
            session_id: Session identifier for privacy isolation
            role: Message role (user or assistant)
            content: The message content
            philosopher_collection: Optional philosopher collection context
            conversation_id: Optional existing conversation ID
            username: Optional user identifier for multi-user support
            session: Optional existing database session

        Returns:
            The created ChatMessage instance

        Raises:
            ChatValidationError: If input validation fails
            ChatDatabaseError: If database operation fails
            ChatPrivacyError: If privacy validation fails
        """
        # Input validation
        if not session_id or not session_id.strip():
            raise ChatValidationError(
                message="Session ID cannot be empty",
                field="session_id",
                value=session_id
            )
        
        if not content or not content.strip():
            raise ChatValidationError(
                message="Message content cannot be empty",
                field="content",
                value=content
            )
        
        if len(content) > 50000:  # Reasonable limit for message content
            raise ChatValidationError(
                message="Message content too long (max 50,000 characters)",
                field="content",
                value=f"Length: {len(content)}"
            )

        # Validate role
        try:
            message_role = MessageRole(role)
        except ValueError:
            raise ChatValidationError(
                message=f"Invalid message role: {role}. Must be 'user' or 'assistant'",
                field="role",
                value=role
            )

        async def _store(db_session: AsyncSession) -> ChatMessage:
            try:
                # Get or create conversation
                if conversation_id:
                    # Use existing conversation with privacy validation
                    conversation = await self._get_conversation_by_id(
                        conversation_id, session_id, db_session
                    )
                    if not conversation:
                        raise ChatPrivacyError(
                            message=f"Conversation {conversation_id} not found or access denied",
                            violation_type="conversation_access",
                            session_id=session_id,
                            details={"conversation_id": conversation_id}
                        )
                else:
                    # Get or create a conversation for this session
                    conversation = await self._get_or_create_conversation(
                        session_id, philosopher_collection, username, db_session
                    )

                # Create the message
                message_id = str(uuid.uuid4())
                message = ChatMessage(
                    message_id=message_id,
                    conversation_id=conversation.conversation_id,
                    session_id=session_id,
                    username=username,
                    role=message_role,
                    content=content,
                    philosopher_collection=philosopher_collection
                )

                db_session.add(message)

                # Note: conversation.updated_at is automatically set by SQLAlchemy onupdate trigger
                db_session.add(conversation)
                
                await db_session.commit()
                await db_session.refresh(message)

                # Invalidate relevant caches after successful commit
                if hasattr(self, 'cache_service') and self.cache_service:
                    await self._invalidate_session_caches(session_id, conversation.conversation_id)

                log.info(f"Stored {role} message for session {session_id} in conversation {conversation.conversation_id}")
                return message

            except ChatPrivacyError:
                await db_session.rollback()
                raise
            except ChatValidationError:
                await db_session.rollback()
                raise
            except IntegrityError as e:
                await db_session.rollback()
                log.error(f"Database integrity error storing message for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Message storage failed due to data integrity constraint",
                    operation="store_message",
                    session_id=session_id,
                    details={"integrity_error": str(e)}
                )
            except OperationalError as e:
                await db_session.rollback()
                log.error(f"Database operational error storing message for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Database connection or operational error",
                    operation="store_message",
                    session_id=session_id,
                    details={"operational_error": str(e)},
                    recoverable=True
                )
            except SQLAlchemyError as e:
                await db_session.rollback()
                log.error(f"SQLAlchemy error storing message for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Database error during message storage",
                    operation="store_message",
                    session_id=session_id,
                    details={"sqlalchemy_error": str(e)}
                )
            except Exception as e:
                await db_session.rollback()
                log.error(f"Unexpected error storing message for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message=f"Unexpected error during message storage: {str(e)}",
                    operation="store_message",
                    session_id=session_id,
                    details={"unexpected_error": str(e)}
                )

        if session:
            return await _store(session)
        else:
            try:
                async with AsyncSessionLocal() as db_session:
                    return await _store(db_session)
            except Exception as e:
                log.error(f"Failed to create database session for message storage: {e}")
                raise ChatDatabaseError(
                    message="Failed to establish database connection",
                    operation="store_message",
                    session_id=session_id,
                    details={"connection_error": str(e)},
                    recoverable=True
                )

    @monitor_chat_operation("get_conversation_history")
    @database_fallback_decorator(fallback_data=[])
    async def get_conversation_history(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        conversation_id: Optional[str] = None,
        username: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> List[ChatMessage]:
        """
        Retrieve conversation history filtered by session_id with pagination and error handling.

        Args:
            session_id: Session identifier for privacy isolation
            limit: Maximum number of messages to return (default: 50)
            offset: Number of messages to skip (default: 0)
            conversation_id: Optional specific conversation to filter by
            username: Optional username for user-specific filtering
            session: Optional existing database session

        Returns:
            List of ChatMessage instances ordered by creation time

        Raises:
            ChatValidationError: If input validation fails
            ChatDatabaseError: If database operation fails
        """
        # Input validation
        if not session_id or not session_id.strip():
            raise ChatValidationError(
                message="Session ID cannot be empty",
                field="session_id",
                value=session_id
            )
        
        if limit <= 0 or limit > 1000:
            raise ChatValidationError(
                message="Limit must be between 1 and 1000",
                field="limit",
                value=limit
            )
        
        if offset < 0:
            raise ChatValidationError(
                message="Offset cannot be negative",
                field="offset",
                value=offset
            )

        # Try cache first for read-only operations (when offset is 0 and limit is reasonable)
        cache_key = None
        if self.cache_service and offset == 0 and limit <= 100:
            cache_key = f"chat_history:{session_id}:{username or 'none'}:{conversation_id or 'all'}:{limit}"
            cached_result = await self.cache_service.get(cache_key, cache_type='chat_history')
            if cached_result is not None:
                log.debug(f"Cache hit for conversation history: {session_id}")
                return cached_result

        async def _get_history(db_session: AsyncSession) -> List[ChatMessage]:
            try:
                # Build optimized query with session filtering (privacy protection)
                statement = select(ChatMessage).where(ChatMessage.session_id == session_id)

                # Add username filter if specified
                if username:
                    statement = statement.where(ChatMessage.username == username)

                # Add conversation filter if specified with privacy validation
                if conversation_id:
                    # Ensure conversation belongs to the session
                    conversation_check = select(ChatConversation).where(
                        and_(
                            ChatConversation.conversation_id == conversation_id,
                            ChatConversation.session_id == session_id
                        )
                    )
                    conv_result = await db_session.execute(conversation_check)
                    if not conv_result.scalars().first():
                        raise ChatPrivacyError(
                            message="Conversation not found or access denied",
                            violation_type="conversation_access",
                            session_id=session_id,
                            details={"conversation_id": conversation_id}
                        )
                    
                    statement = statement.where(ChatMessage.conversation_id == conversation_id)
                
                # Order by creation time (oldest first for conversation flow)
                statement = statement.order_by(ChatMessage.created_at.asc())
                
                # Apply pagination
                statement = statement.offset(offset).limit(limit)

                result = await db_session.execute(statement)
                messages = result.scalars().all()

                # Cache the result if caching is enabled and this is a cacheable query
                if self.cache_service and cache_key and offset == 0:
                    await self.cache_service.set(cache_key, messages, ttl=300, cache_type='chat_history')  # 5 minute cache
                    log.debug(f"Cached conversation history for session {session_id}")

                log.info(f"Retrieved {len(messages)} messages for session {session_id} (offset: {offset}, limit: {limit})")
                return messages

            except ChatPrivacyError:
                raise
            except ChatValidationError:
                raise
            except OperationalError as e:
                log.error(f"Database operational error retrieving history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Database connection error during history retrieval",
                    operation="get_conversation_history",
                    session_id=session_id,
                    details={"operational_error": str(e)},
                    recoverable=True
                )
            except SQLAlchemyError as e:
                log.error(f"Database error retrieving history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Database error during history retrieval",
                    operation="get_conversation_history",
                    session_id=session_id,
                    details={"sqlalchemy_error": str(e)}
                )
            except Exception as e:
                log.error(f"Unexpected error retrieving history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message=f"Unexpected error during history retrieval: {str(e)}",
                    operation="get_conversation_history",
                    session_id=session_id,
                    details={"unexpected_error": str(e)}
                )

        if session:
            return await _get_history(session)
        else:
            try:
                async with AsyncSessionLocal() as db_session:
                    return await _get_history(db_session)
            except Exception as e:
                log.error(f"Failed to create database session for history retrieval: {e}")
                raise ChatDatabaseError(
                    message="Failed to establish database connection",
                    operation="get_conversation_history",
                    session_id=session_id,
                    details={"connection_error": str(e)},
                    recoverable=True
                )

    async def get_conversations(
        self,
        session_id: str,
        limit: int = 20,
        offset: int = 0,
        session: Optional[AsyncSession] = None
    ) -> List[ChatConversation]:
        """
        Retrieve conversation list with metadata for a session.

        Args:
            session_id: Session identifier for privacy isolation
            limit: Maximum number of conversations to return (default: 20)
            offset: Number of conversations to skip (default: 0)
            session: Optional existing database session

        Returns:
            List of ChatConversation instances with message counts
        """
        # Try cache first for first page requests
        cache_key = None
        if self.cache_service and offset == 0 and limit <= 50:
            cache_key = f"conversations:{session_id}:{limit}"
            cached_result = await self.cache_service.get(cache_key, cache_type='chat_history')
            if cached_result is not None:
                log.debug(f"Cache hit for conversations: {session_id}")
                return cached_result

        async def _get_conversations(db_session: AsyncSession) -> List[ChatConversation]:
            try:
                # Optimized query with proper indexing
                statement = (
                    select(ChatConversation)
                    .where(ChatConversation.session_id == session_id)
                    .options(selectinload(ChatConversation.messages))
                    .order_by(ChatConversation.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )

                result = await db_session.execute(statement)
                conversations = result.scalars().all()

                # Cache the result for first page requests
                if self.cache_service and cache_key and offset == 0:
                    await self.cache_service.set(cache_key, conversations, ttl=180, cache_type='chat_history')  # 3 minute cache
                    log.debug(f"Cached conversations for session {session_id}")

                log.info(f"Retrieved {len(conversations)} conversations for session {session_id}")
                return conversations

            except Exception as e:
                log.error(f"Failed to retrieve conversations for session {session_id}: {e}")
                raise

        if session:
            return await _get_conversations(session)
        else:
            async with AsyncSessionLocal() as db_session:
                return await _get_conversations(db_session)

    async def get_conversation_count(
        self,
        session_id: str,
        username: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> int:
        """
        Get total count of conversations for a session.

        Args:
            session_id: Session identifier
            username: Optional username for user-specific filtering
            session: Optional existing database session

        Returns:
            Total number of conversations for the session
        """
        # Try cache first for count queries
        cache_key = f"conversation_count:{session_id}:{username or 'none'}"
        if self.cache_service:
            cached_count = await self.cache_service.get(cache_key, cache_type='chat_history')
            if cached_count is not None:
                log.debug(f"Cache hit for conversation count: {session_id}")
                return cached_count

        async def _get_count(db_session: AsyncSession) -> int:
            try:
                # Optimized count query using index
                statement = select(func.count(ChatConversation.id)).where(
                    ChatConversation.session_id == session_id
                )

                if username:
                    statement = statement.where(ChatConversation.username == username)

                result = await db_session.execute(statement)
                count = result.scalar() or 0

                # Cache the count result
                if self.cache_service:
                    await self.cache_service.set(cache_key, count, ttl=300, cache_type='chat_history')  # 5 minute cache
                    log.debug(f"Cached conversation count for session {session_id}")

                return count

            except Exception as e:
                log.error(f"Failed to get conversation count for session {session_id}: {e}")
                raise

        if session:
            return await _get_count(session)
        else:
            async with AsyncSessionLocal() as db_session:
                return await _get_count(db_session)

    async def get_message_count(
        self,
        session_id: str,
        conversation_id: Optional[str] = None,
        username: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> int:
        """
        Get total count of messages for a session or specific conversation.

        Args:
            session_id: Session identifier
            conversation_id: Optional specific conversation
            username: Optional username for user-specific filtering
            session: Optional existing database session

        Returns:
            Total number of messages
        """
        # Try cache first for count queries
        cache_key = f"message_count:{session_id}:{username or 'none'}:{conversation_id or 'all'}"
        if self.cache_service:
            cached_count = await self.cache_service.get(cache_key, cache_type='chat_history')
            if cached_count is not None:
                log.debug(f"Cache hit for message count: {session_id}")
                return cached_count

        async def _get_count(db_session: AsyncSession) -> int:
            try:
                # Optimized count query using composite indexes
                statement = select(func.count(ChatMessage.id)).where(
                    ChatMessage.session_id == session_id
                )

                if username:
                    statement = statement.where(ChatMessage.username == username)

                if conversation_id:
                    statement = statement.where(ChatMessage.conversation_id == conversation_id)

                result = await db_session.execute(statement)
                count = result.scalar() or 0

                # Cache the count result
                if self.cache_service:
                    await self.cache_service.set(cache_key, count, ttl=300, cache_type='chat_history')  # 5 minute cache
                    log.debug(f"Cached message count for session {session_id}")

                return count

            except Exception as e:
                log.error(f"Failed to get message count for session {session_id}: {e}")
                raise

        if session:
            return await _get_count(session)
        else:
            async with AsyncSessionLocal() as db_session:
                return await _get_count(db_session)

    @monitor_chat_operation("delete_user_history")
    async def delete_user_history(
        self,
        session_id: str,
        conversation_id: Optional[str] = None,
        session: Optional[AsyncSession] = None
    ) -> bool:
        """
        Delete chat history for a user session with comprehensive error handling.

        Args:
            session_id: Session identifier for privacy isolation
            conversation_id: Optional specific conversation to delete
            session: Optional existing database session

        Returns:
            True if deletion was successful, False otherwise
            
        Raises:
            ChatValidationError: If input validation fails
            ChatDatabaseError: If database operation fails
            ChatPrivacyError: If privacy validation fails
        """
        # Input validation
        if not session_id or not session_id.strip():
            raise ChatValidationError(
                message="Session ID cannot be empty",
                field="session_id",
                value=session_id
            )

        async def _delete_history(db_session: AsyncSession) -> bool:
            try:
                deleted_messages = 0
                deleted_conversations = 0
                
                if conversation_id:
                    # Privacy validation - ensure conversation belongs to session
                    conversation_check = select(ChatConversation).where(
                        and_(
                            ChatConversation.conversation_id == conversation_id,
                            ChatConversation.session_id == session_id
                        )
                    )
                    conv_result = await db_session.execute(conversation_check)
                    conversation = conv_result.scalars().first()
                    
                    if not conversation:
                        raise ChatPrivacyError(
                            message="Conversation not found or access denied",
                            violation_type="conversation_deletion",
                            session_id=session_id,
                            details={"conversation_id": conversation_id}
                        )
                    
                    # Delete specific conversation and its messages
                    # First delete messages
                    message_statement = select(ChatMessage).where(
                        and_(
                            ChatMessage.session_id == session_id,
                            ChatMessage.conversation_id == conversation_id
                        )
                    )
                    message_result = await db_session.execute(message_statement)
                    messages = message_result.scalars().all()
                    
                    for message in messages:
                        await db_session.delete(message)
                        deleted_messages += 1

                    # Then delete conversation
                    await db_session.delete(conversation)
                    deleted_conversations += 1

                    await db_session.commit()
                    
                    # Invalidate caches after successful deletion
                    if hasattr(self, 'cache_service') and self.cache_service:
                        await self._invalidate_session_caches(session_id, conversation_id)
                    
                    log.info(f"Deleted conversation {conversation_id} for session {session_id} "
                            f"({deleted_messages} messages, {deleted_conversations} conversations)")
                else:
                    # Delete all history for the session
                    # First delete all messages
                    message_statement = select(ChatMessage).where(ChatMessage.session_id == session_id)
                    message_result = await db_session.execute(message_statement)
                    messages = message_result.scalars().all()
                    
                    for message in messages:
                        await db_session.delete(message)
                        deleted_messages += 1

                    # Then delete all conversations
                    conversation_statement = select(ChatConversation).where(
                        ChatConversation.session_id == session_id
                    )
                    conversation_result = await db_session.execute(conversation_statement)
                    conversations = conversation_result.scalars().all()
                    
                    for conversation in conversations:
                        await db_session.delete(conversation)
                        deleted_conversations += 1

                    await db_session.commit()
                    
                    # Invalidate all caches for this session after successful deletion
                    if hasattr(self, 'cache_service') and self.cache_service:
                        await self._invalidate_all_session_caches(session_id)
                    
                    log.info(f"Deleted all chat history for session {session_id} "
                            f"({deleted_messages} messages, {deleted_conversations} conversations)")

                return True

            except ChatPrivacyError:
                await db_session.rollback()
                raise
            except ChatValidationError:
                await db_session.rollback()
                raise
            except IntegrityError as e:
                await db_session.rollback()
                log.error(f"Database integrity error deleting history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="History deletion failed due to data integrity constraint",
                    operation="delete_user_history",
                    session_id=session_id,
                    details={"integrity_error": str(e)}
                )
            except OperationalError as e:
                await db_session.rollback()
                log.error(f"Database operational error deleting history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Database connection or operational error during deletion",
                    operation="delete_user_history",
                    session_id=session_id,
                    details={"operational_error": str(e)},
                    recoverable=True
                )
            except SQLAlchemyError as e:
                await db_session.rollback()
                log.error(f"SQLAlchemy error deleting history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message="Database error during history deletion",
                    operation="delete_user_history",
                    session_id=session_id,
                    details={"sqlalchemy_error": str(e)}
                )
            except Exception as e:
                await db_session.rollback()
                log.error(f"Unexpected error deleting history for session {session_id}: {e}")
                raise ChatDatabaseError(
                    message=f"Unexpected error during history deletion: {str(e)}",
                    operation="delete_user_history",
                    session_id=session_id,
                    details={"unexpected_error": str(e)}
                )

        if session:
            return await _delete_history(session)
        else:
            try:
                async with AsyncSessionLocal() as db_session:
                    return await _delete_history(db_session)
            except Exception as e:
                log.error(f"Failed to create database session for history deletion: {e}")
                raise ChatDatabaseError(
                    message="Failed to establish database connection",
                    operation="delete_user_history",
                    session_id=session_id,
                    details={"connection_error": str(e)},
                    recoverable=True
                )

    async def update_message_qdrant_id(
        self,
        message_id: str,
        qdrant_point_id: str,
        session: Optional[AsyncSession] = None
    ) -> bool:
        """
        Update a message with its corresponding Qdrant point ID.

        Args:
            message_id: Message identifier
            qdrant_point_id: Qdrant point ID for vector search
            session: Optional existing database session

        Returns:
            True if update was successful, False otherwise
        """
        async def _update(db_session: AsyncSession) -> bool:
            try:
                statement = select(ChatMessage).where(ChatMessage.message_id == message_id)
                result = await db_session.execute(statement)
                message = result.scalars().first()

                if not message:
                    log.warning(f"Message {message_id} not found for Qdrant ID update")
                    return False

                message.qdrant_point_id = qdrant_point_id
                db_session.add(message)
                await db_session.commit()

                log.info(f"Updated message {message_id} with Qdrant point ID {qdrant_point_id}")
                return True

            except Exception as e:
                await db_session.rollback()
                log.error(f"Failed to update message {message_id} with Qdrant ID: {e}")
                return False

        if session:
            return await _update(session)
        else:
            async with AsyncSessionLocal() as db_session:
                return await _update(db_session)

    async def _get_or_create_conversation(
        self,
        session_id: str,
        philosopher_collection: Optional[str],
        username: Optional[str],
        db_session: AsyncSession
    ) -> ChatConversation:
        """
        Get the most recent conversation for a session or create a new one.

        Args:
            session_id: Session identifier
            philosopher_collection: Philosopher collection context
            username: Optional user identifier
            db_session: Database session

        Returns:
            ChatConversation instance
        """
        # Look for the most recent conversation for this session
        statement = (
            select(ChatConversation)
            .where(ChatConversation.session_id == session_id)
            .order_by(ChatConversation.updated_at.desc())
            .limit(1)
        )

        result = await db_session.execute(statement)
        existing_conversation = result.scalars().first()

        # Create new conversation if none exists or if philosopher collection changed
        if (not existing_conversation or
            (philosopher_collection and
             existing_conversation.philosopher_collection != philosopher_collection)):

            conversation_id = str(uuid.uuid4())
            conversation = ChatConversation(
                conversation_id=conversation_id,
                session_id=session_id,
                username=username,
                philosopher_collection=philosopher_collection
            )

            db_session.add(conversation)
            await db_session.flush()  # Ensure it's available for message creation

            log.info(f"Created new conversation {conversation_id} for session {session_id}{f' (user: {username})' if username else ''}")
            return conversation
        else:
            return existing_conversation

    async def _get_conversation_by_id(
        self,
        conversation_id: str,
        session_id: str,
        db_session: AsyncSession
    ) -> Optional[ChatConversation]:
        """
        Get a specific conversation by ID with session validation.

        Args:
            conversation_id: Conversation identifier
            session_id: Session identifier for privacy validation
            db_session: Database session

        Returns:
            ChatConversation instance if found and belongs to session, None otherwise
        """
        statement = select(ChatConversation).where(
            and_(
                ChatConversation.conversation_id == conversation_id,
                ChatConversation.session_id == session_id
            )
        )
        
        result = await db_session.execute(statement)
        return result.scalars().first()

    async def _invalidate_session_caches(self, session_id: str, conversation_id: Optional[str] = None):
        """Invalidate cached data for a session after modifications."""
        if not self.cache_service:
            return
            
        try:
            # Invalidate conversation history caches
            patterns = [
                f"chat_history:{session_id}:*",
                f"conversations:{session_id}:*",
                f"conversation_count:{session_id}",
                f"message_count:{session_id}:*"
            ]
            
            if conversation_id:
                patterns.append(f"message_count:{session_id}:{conversation_id}")
            
            for pattern in patterns:
                await self.cache_service.clear_cache(pattern)
                
            log.debug(f"Invalidated caches for session {session_id}")
            
        except Exception as e:
            log.warning(f"Failed to invalidate caches for session {session_id}: {e}")

    async def _invalidate_all_session_caches(self, session_id: str):
        """Invalidate all cached data for a session."""
        if not self.cache_service:
            return

        try:
            # Clear all cache entries for this session
            patterns = [
                f"chat_history:{session_id}:*",
                f"conversations:{session_id}:*",
                f"conversation_count:{session_id}",
                f"message_count:{session_id}:*"
            ]

            for pattern in patterns:
                await self.cache_service.clear_cache(pattern)

            log.debug(f"Invalidated all caches for session {session_id}")

        except Exception as e:
            log.warning(f"Failed to invalidate all caches for session {session_id}: {e}")
