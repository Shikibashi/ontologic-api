"""
Chat History API Router.

This module provides REST API endpoints for managing chat history including
conversation retrieval, semantic search, and history management with proper
session isolation and privacy protection.
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Request, Path
from datetime import datetime, timezone

from app.core.dependencies import ChatHistoryServiceDep, ChatQdrantServiceDep
from app.core.rate_limiting import limiter, get_default_limit, get_heavy_limit
from app.core.http_error_guard import http_error_guard
from app.core.logger import log
from app.core.chat_models import (
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatMessageRequest,
    ChatSearchRequest,
    ChatSearchResponse,
    ChatSearchResultItem,
    ChatConversationsResponse,
    ChatConversationResponse,
    ChatDeletionResponse
)
from app.core.exceptions import LLMError, LLMTimeoutError, LLMUnavailableError
from app.config.settings import get_settings
from app.core.error_responses import (
    create_validation_error,
    create_not_found_error,
    create_internal_error,
    create_authentication_error,
    create_authorization_error,
    create_service_unavailable_error,
    create_timeout_error
)


router = APIRouter(prefix="/chat", tags=["Chat History"])


def is_chat_history_enabled() -> bool:
    """Check if chat history feature is enabled in configuration."""
    settings = get_settings()
    return settings.chat_history


def validate_session_id(session_id: str, request_id: Optional[str] = None) -> None:
    """
    Validate session ID format and security.

    Args:
        session_id: Session identifier to validate
        request_id: Optional request ID for tracking

    Raises:
        HTTPException: If session ID is invalid
    """
    if not session_id or not session_id.strip():
        error = create_validation_error(
            field="session_id",
            message="Session ID cannot be empty",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    if len(session_id) > 255:
        error = create_validation_error(
            field="session_id",
            message="Session ID too long (max 255 characters)",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    # Basic security check - prevent path traversal attempts
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        error = create_validation_error(
            field="session_id",
            message="Invalid session ID format",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    status_code=201,
    summary="Store a chat message",
    description="""
    Store a new chat message in the history database.

    This endpoint persists chat messages to both PostgreSQL and Qdrant vector database
    with proper session isolation and optional username tracking.

    **Privacy**: Messages are isolated by session_id.
    **Username tracking**: Optional username parameter for multi-user support.
    """
)
@limiter.limit(get_default_limit)
@http_error_guard
async def store_chat_message(
    request: Request,
    message_request: ChatMessageRequest,
    chat_history_service: ChatHistoryServiceDep = None,
    chat_qdrant_service: ChatQdrantServiceDep = None
) -> ChatMessageResponse:
    """
    Store a chat message with proper session isolation.

    Args:
        message_request: Message data including session_id, role, content, and optional username
        chat_history_service: Injected chat history service
        chat_qdrant_service: Injected chat Qdrant service

    Returns:
        ChatMessageResponse with the stored message data

    Raises:
        HTTPException: If chat history disabled, invalid request, or storage fails
    """
    request_id = getattr(request.state, 'request_id', None)

    # Check if chat history feature is enabled
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat history",
            message="Chat history feature is not enabled",
            request_id=request_id
        )
        raise HTTPException(status_code=503, detail=error.model_dump())

    # Validate session ID
    validate_session_id(message_request.session_id, request_id)

    try:
        log.info(f"Storing {message_request.role} message for session {message_request.session_id}")

        # Store message in PostgreSQL
        stored_message = await chat_history_service.store_message(
            session_id=message_request.session_id,
            role=message_request.role,
            content=message_request.content,
            philosopher_collection=message_request.philosopher_collection,
            conversation_id=message_request.conversation_id,
            username=message_request.username
        )

        # Upload to Qdrant vector database (asynchronously, don't block on failure)
        try:
            point_ids = await chat_qdrant_service.upload_message_to_qdrant(stored_message)
            if point_ids and len(point_ids) > 0:
                # Update message with first Qdrant point ID
                await chat_history_service.update_message_qdrant_id(
                    stored_message.message_id,
                    point_ids[0]
                )
        except Exception as qdrant_error:
            log.warning(f"Failed to upload message to Qdrant (non-blocking): {qdrant_error}")

        # Convert to response format
        response = ChatMessageResponse(
            message_id=stored_message.message_id,
            conversation_id=stored_message.conversation_id,
            session_id=stored_message.session_id,
            username=stored_message.username,
            role=stored_message.role.value,
            content=stored_message.content,
            philosopher_collection=stored_message.philosopher_collection,
            created_at=stored_message.created_at
        )

        log.info(f"Successfully stored message {stored_message.message_id} for session {message_request.session_id}")
        return response

    except Exception as e:
        log.error(f"Failed to store message for session {message_request.session_id}: {e}")
        error = create_internal_error(
            message="Failed to store chat message",
            error_type="storage_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get(
    "/history/{session_id}",
    response_model=ChatHistoryResponse,
    summary="Get chat history for a session",
    description="""
    Retrieve paginated conversation history for a specific session.

    This endpoint returns all messages for a given session with proper pagination
    and privacy isolation. Only messages belonging to the specified session are returned.

    **Privacy**: Messages are strictly filtered by session_id to ensure complete
    privacy isolation between different users/sessions.
    **Username filtering**: Optional username parameter for user-specific filtering.
    """
)
@limiter.limit(get_default_limit)
@http_error_guard
async def get_chat_history(
    request: Request,
    session_id: str = Path(..., description="Session identifier for privacy isolation"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of messages to return"),
    offset: int = Query(0, ge=0, description="Number of messages to skip for pagination"),
    conversation_id: Optional[str] = Query(None, description="Optional specific conversation filter"),
    username: Optional[str] = Query(None, description="Optional username for user-specific filtering"),
    chat_history_service: ChatHistoryServiceDep = None
) -> ChatHistoryResponse:
    """
    Get paginated chat history for a session.
    
    Args:
        session_id: Session identifier for privacy isolation
        limit: Maximum number of messages to return (1-100)
        offset: Number of messages to skip for pagination
        conversation_id: Optional filter for specific conversation
        chat_history_service: Injected chat history service
        
    Returns:
        ChatHistoryResponse with paginated messages and metadata
        
    Raises:
        HTTPException: If chat history is disabled, session invalid, or service error
    """
    request_id = getattr(request.state, 'request_id', None)

    # Check if chat history feature is enabled
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat history",
            message="Chat history feature is not enabled",
            request_id=request_id
        )
        raise HTTPException(status_code=503, detail=error.model_dump())

    # Validate session ID
    validate_session_id(session_id, request_id)
    
    try:
        log.info(f"Retrieving chat history for session {session_id} (limit: {limit}, offset: {offset})")
        
        # Get messages with pagination
        messages = await chat_history_service.get_conversation_history(
            session_id=session_id,
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            username=username
        )

        # Get total count for pagination metadata
        total_count = await chat_history_service.get_message_count(
            session_id=session_id,
            conversation_id=conversation_id,
            username=username
        )
        
        # Convert to response format
        message_responses = [
            ChatMessageResponse(
                message_id=msg.message_id,
                conversation_id=msg.conversation_id,
                session_id=msg.session_id,
                username=msg.username,
                role=msg.role.value,
                content=msg.content,
                philosopher_collection=msg.philosopher_collection,
                created_at=msg.created_at
            )
            for msg in messages
        ]
        
        # Calculate pagination metadata
        has_more = (offset + len(messages)) < total_count
        
        response = ChatHistoryResponse(
            messages=message_responses,
            total_count=total_count,
            has_more=has_more,
            offset=offset,
            limit=limit
        )
        
        log.info(
            f"Retrieved {len(messages)} messages for session {session_id} "
            f"(total: {total_count}, has_more: {has_more})"
        )
        
        return response
        
    except Exception as e:
        log.error(f"Failed to retrieve chat history for session {session_id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve chat history",
            error_type="retrieval_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.post(
    "/search",
    response_model=ChatSearchResponse,
    summary="Search chat history",
    description="""
    Perform semantic search across chat history for a specific session.
    
    This endpoint uses vector similarity search to find relevant messages based on
    content similarity. Results are ranked by relevance score and strictly filtered
    by session_id to ensure privacy isolation.
    
    **Privacy**: Search results are limited to the specified session only.
    **Performance**: Results are cached and optimized for fast retrieval.
    """
)
@limiter.limit(get_heavy_limit)
@http_error_guard
async def search_chat_history(
    request: Request,
    search_request: ChatSearchRequest,
    chat_qdrant_service: ChatQdrantServiceDep = None
) -> ChatSearchResponse:
    """
    Search chat history using semantic vector search.
    
    Args:
        search_request: Search parameters including session_id, query, and filters
        chat_qdrant_service: Injected chat Qdrant service
        
    Returns:
        ChatSearchResponse with ranked search results
        
    Raises:
        HTTPException: If chat history disabled, invalid request, or search fails
    """
    request_id = getattr(request.state, 'request_id', None)

    # Check if chat history feature is enabled
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat history",
            message="Chat history feature is not enabled",
            request_id=request_id
        )
        raise HTTPException(status_code=503, detail=error.model_dump())

    # Validate session ID
    validate_session_id(search_request.session_id, request_id)

    # Validate query
    if not search_request.query.strip():
        error = create_validation_error(
            field="query",
            message="Search query cannot be empty",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())
    
    try:
        log.info(
            f"Searching chat history for session {search_request.session_id} "
            f"with query: '{search_request.query[:100]}...'"
        )
        
        # Perform semantic search with session filtering
        search_results = await chat_qdrant_service.search_messages(
            session_id=search_request.session_id,
            query=search_request.query,
            limit=search_request.limit,
            philosopher_filter=search_request.philosopher_filter,
            username=search_request.username
        )
        
        # Convert to response format
        result_items = []
        for result in search_results:
            # Parse created_at if it's a string
            created_at = result.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except ValueError:
                    created_at = datetime.now(timezone.utc)  # Fallback to current time
            elif not isinstance(created_at, datetime):
                created_at = datetime.now(timezone.utc)  # Fallback to current time
            
            result_item = ChatSearchResultItem(
                message_id=result.get("message_id"),
                conversation_id=result.get("conversation_id"),
                session_id=result.get("session_id"),
                username=result.get("username"),
                role=result.get("role"),
                content=result.get("content"),
                philosopher_collection=result.get("philosopher_collection"),
                created_at=created_at,
                relevance_score=result.get("relevance_score", 0.0),
                source_type="chat"
            )
            result_items.append(result_item)
        
        response = ChatSearchResponse(
            results=result_items,
            total_found=len(result_items),
            query=search_request.query,
            session_id=search_request.session_id
        )
        
        log.info(
            f"Found {len(result_items)} relevant messages for session {search_request.session_id}"
        )
        
        return response
        
    except LLMTimeoutError as e:
        log.warning(f"Chat search timed out for session {search_request.session_id}: {e}")
        error = create_timeout_error(
            timeout_seconds=120,
            operation="search request",
            request_id=request_id
        )
        raise HTTPException(status_code=504, detail=error.model_dump())
    except LLMUnavailableError as e:
        log.error(f"Chat search service unavailable: {e}")
        error = create_service_unavailable_error(
            service="search",
            message="Search service temporarily unavailable",
            request_id=request_id
        )
        raise HTTPException(status_code=503, detail=error.model_dump())
    except LLMError as e:
        log.error(f"Chat search failed: {e}")
        error = create_internal_error(
            message="Search operation failed",
            error_type="search_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())
    except Exception as e:
        log.error(f"Unexpected error during chat search: {e}")
        error = create_internal_error(
            message="Failed to search chat history",
            error_type="search_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.delete(
    "/history/{session_id}",
    response_model=ChatDeletionResponse,
    summary="Delete chat history for a session",
    description="""
    Delete all chat history for a specific session.
    
    This endpoint removes all conversations and messages for the given session
    from both PostgreSQL and Qdrant vector database. The operation is irreversible.
    
    **Privacy**: Only data belonging to the specified session is deleted.
    **Cleanup**: Removes data from both structured (PostgreSQL) and vector (Qdrant) storage.
    """
)
@limiter.limit(get_default_limit)
@http_error_guard
async def delete_chat_history(
    request: Request,
    session_id: str = Path(..., description="Session identifier for history deletion"),
    chat_history_service: ChatHistoryServiceDep = None,
    chat_qdrant_service: ChatQdrantServiceDep = None
) -> ChatDeletionResponse:
    """
    Delete all chat history for a session.
    
    Args:
        session_id: Session identifier for privacy isolation
        chat_history_service: Injected chat history service
        chat_qdrant_service: Injected chat Qdrant service
        
    Returns:
        ChatDeletionResponse with deletion status and counts
        
    Raises:
        HTTPException: If chat history disabled, invalid session, or deletion fails
    """
    request_id = getattr(request.state, 'request_id', None)

    # Check if chat history feature is enabled
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat history",
            message="Chat history feature is not enabled",
            request_id=request_id
        )
        raise HTTPException(status_code=503, detail=error.model_dump())

    # Validate session ID
    validate_session_id(session_id, request_id)

    try:
        log.info(f"Deleting all chat history for session {session_id}")
        
        # Get counts before deletion for response
        conversation_count = await chat_history_service.get_conversation_count(session_id)
        message_count = await chat_history_service.get_message_count(session_id)
        
        # Delete from PostgreSQL
        postgres_success = await chat_history_service.delete_user_history(session_id)
        
        # Delete from Qdrant
        qdrant_success = True
        try:
            await chat_qdrant_service.delete_user_messages(session_id)
        except Exception as qdrant_error:
            log.warning(f"Failed to delete Qdrant data for session {session_id}: {qdrant_error}")
            qdrant_success = False
        
        # Determine overall success
        overall_success = postgres_success and qdrant_success
        
        if overall_success:
            message = "Chat history successfully deleted"
        elif postgres_success:
            message = "Chat history deleted from database, but vector data cleanup may be incomplete"
        else:
            message = "Failed to delete chat history"
        
        response = ChatDeletionResponse(
            success=overall_success,
            message=message,
            deleted_conversations=conversation_count if postgres_success else 0,
            deleted_messages=message_count if postgres_success else 0,
            session_id=session_id
        )
        
        log.info(
            f"Chat history deletion for session {session_id}: "
            f"success={overall_success}, conversations={conversation_count}, messages={message_count}"
        )
        
        return response
        
    except Exception as e:
        log.error(f"Failed to delete chat history for session {session_id}: {e}")
        error = create_internal_error(
            message="Failed to delete chat history",
            error_type="deletion_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@router.get(
    "/conversations/{session_id}",
    response_model=ChatConversationsResponse,
    summary="Get conversations for a session",
    description="""
    Retrieve a list of conversations for a specific session with metadata.
    
    This endpoint returns conversation summaries including message counts,
    timestamps, and associated philosopher collections. Results are paginated
    and ordered by most recent activity.
    
    **Privacy**: Only conversations belonging to the specified session are returned.
    **Metadata**: Includes conversation titles, message counts, and activity timestamps.
    """
)
@limiter.limit(get_default_limit)
@http_error_guard
async def get_conversations(
    request: Request,
    session_id: str = Path(..., description="Session identifier for privacy isolation"),
    limit: int = Query(20, ge=1, le=50, description="Maximum number of conversations to return"),
    offset: int = Query(0, ge=0, description="Number of conversations to skip for pagination"),
    chat_history_service: ChatHistoryServiceDep = None
) -> ChatConversationsResponse:
    """
    Get paginated conversation list for a session.
    
    Args:
        session_id: Session identifier for privacy isolation
        limit: Maximum number of conversations to return (1-50)
        offset: Number of conversations to skip for pagination
        chat_history_service: Injected chat history service
        
    Returns:
        ChatConversationsResponse with paginated conversations and metadata
        
    Raises:
        HTTPException: If chat history disabled, invalid session, or service error
    """
    request_id = getattr(request.state, 'request_id', None)

    # Check if chat history feature is enabled
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat history",
            message="Chat history feature is not enabled",
            request_id=request_id
        )
        raise HTTPException(status_code=503, detail=error.model_dump())

    # Validate session ID
    validate_session_id(session_id, request_id)

    try:
        log.info(f"Retrieving conversations for session {session_id} (limit: {limit}, offset: {offset})")
        
        # Get conversations with pagination
        conversations = await chat_history_service.get_conversations(
            session_id=session_id,
            limit=limit,
            offset=offset
        )
        
        # Get total count for pagination metadata
        total_count = await chat_history_service.get_conversation_count(session_id)
        
        # Convert to response format with message counts
        conversation_responses = []
        for conv in conversations:
            # Count messages in this conversation
            message_count = len(conv.messages) if hasattr(conv, 'messages') and conv.messages else 0
            
            # If messages weren't loaded, get count separately
            if message_count == 0:
                message_count = await chat_history_service.get_message_count(
                    session_id=session_id,
                    conversation_id=conv.conversation_id
                )
            
            conversation_response = ChatConversationResponse(
                conversation_id=conv.conversation_id,
                session_id=conv.session_id,
                username=conv.username,
                title=conv.title,
                philosopher_collection=conv.philosopher_collection,
                message_count=message_count,
                created_at=conv.created_at,
                updated_at=conv.updated_at
            )
            conversation_responses.append(conversation_response)
        
        # Calculate pagination metadata
        has_more = (offset + len(conversations)) < total_count
        
        response = ChatConversationsResponse(
            conversations=conversation_responses,
            total_count=total_count,
            has_more=has_more,
            offset=offset,
            limit=limit
        )
        
        log.info(
            f"Retrieved {len(conversations)} conversations for session {session_id} "
            f"(total: {total_count}, has_more: {has_more})"
        )
        
        return response

    except Exception as e:
        log.error(f"Failed to retrieve conversations for session {session_id}: {e}")
        error = create_internal_error(
            message="Failed to retrieve conversations",
            error_type="retrieval_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())