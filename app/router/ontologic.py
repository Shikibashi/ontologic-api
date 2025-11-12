from typing import Annotated, List, Any, Optional, AsyncGenerator
import time
import json
import re
from fastapi import APIRouter, Query, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from app.config.settings import get_settings
from app.core.dependencies import (
    LLMManagerDep,
    QdrantManagerDep,
    CacheServiceDep,
    ChatHistoryServiceDep,
    ChatQdrantServiceDep,
    SubscriptionManagerDep,
)
from app.core.subscription_helpers import (
    check_subscription_access,
    track_subscription_usage,
)
from app.core.rate_limiting import limiter, get_default_limit, get_streaming_limit, get_heavy_limit
from app.core.user_models import User
from app.core.auth_helpers import (
    get_optional_user_with_logging,
    get_username_from_user,
)
from app.core.llm_response_processor import LLMResponseProcessor
from app.core.http_error_guard import http_error_guard
from app.core.logger import log
from app.core.qdrant_helpers import check_collection_exists, CollectionCheckResult
from app.core.constants import (
    CACHE_KEY_PHILOSOPHER_COLLECTIONS,
    PHILOSOPHER_COLLECTIONS_CACHE_TTL,
)
from app.core.collection_filters import filter_philosopher_collections
from app.core.models import (
    HybridQueryRequest,
    AskPhilosophyResponse,
    ConversationMessage,
)
from app.services.monitoring_helpers import safe_record_metric
from app.core.exceptions import (
    LLMError,
    LLMTimeoutError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.core.error_responses import (
    create_timeout_error,
    create_validation_error,
    create_service_unavailable_error,
    create_invalid_response_error,
    create_internal_error,
    create_authorization_error,
    create_not_found_error,
    create_conflict_error,
    create_authentication_error,
)
from app.core.philosopher_loader import _philosopher_loader
from app.core.constants import (
    LLM_QUERY_CACHE_TTL,
    CHAT_CONTEXT_WINDOW_CHARS,
    CONTEXT_BUFFER_TOKENS,
    CHARS_PER_TOKEN_ESTIMATE,
    AVERAGE_MESSAGE_LENGTH_CHARS,
    MAX_CONVERSATION_HISTORY_MESSAGES,
    DEFAULT_PDF_CONTEXT_LIMIT,
)
from app.services.chat_monitoring import chat_monitoring, MetricType


router = APIRouter()


def _get_available_philosopher_collections() -> List[str]:
    """Get list of available philosopher collection names."""
    # Include both philosopher-specific collections and special collections
    philosopher_collections = _philosopher_loader.available_philosophers.copy()
    special_collections = ["Meta Collection", "Combined Collection"]
    return philosopher_collections + special_collections

def _normalize_collection_name(collection: str) -> str:
    """
    Normalize collection name to match existing Qdrant collections.

    Maps lowercase philosopher names to proper case collection names.
    Raises ValueError if the match is ambiguous.
    Examples: "aristotle" -> "Aristotle", "immanuel kant" -> "Immanuel Kant"

    Raises:
        ValueError: If multiple philosophers match the search term (ambiguous)
    """
    # Create mapping from lowercase to proper case
    name_mapping = {name.lower(): name for name in _philosopher_loader.available_philosophers}

    # Try exact match first
    normalized = name_mapping.get(collection.lower())
    if normalized:
        return normalized

    search_term = collection.lower().strip()

    # Stage 1: Word-boundary matches to avoid substring false positives
    exact_word_matches: List[str] = []
    for lower_name, proper_name in name_mapping.items():
        if re.search(r"\b" + re.escape(search_term) + r"\b", lower_name):
            exact_word_matches.append(proper_name)

    if exact_word_matches:
        if len(exact_word_matches) > 1:
            log.warning(
                "Ambiguous collection name '%s' matches multiple: %s.",
                collection,
                exact_word_matches,
            )
            raise ValueError(f"Ambiguous match: {', '.join(exact_word_matches)}")
        return exact_word_matches[0]

    # Stage 2: Prefix/suffix matches
    prefix_suffix_matches: List[str] = []
    for lower_name, proper_name in name_mapping.items():
        if lower_name.startswith(search_term) or lower_name.endswith(search_term):
            prefix_suffix_matches.append(proper_name)

    if prefix_suffix_matches:
        if len(prefix_suffix_matches) > 1:
            log.warning(
                "Ambiguous prefix/suffix match for collection '%s': %s.",
                collection,
                prefix_suffix_matches,
            )
            raise ValueError(f"Ambiguous match: {', '.join(prefix_suffix_matches)}")
        return prefix_suffix_matches[0]

    # Stage 3: Substring matching (fallback for backward compatibility)
    substring_matches: List[str] = []
    for lower_name, proper_name in name_mapping.items():
        if search_term in lower_name or lower_name in search_term:
            substring_matches.append(proper_name)

    if substring_matches:
        if len(substring_matches) > 1:
            log.warning(
                "Ambiguous substring match for collection '%s': %s.",
                collection,
                substring_matches,
            )
            raise ValueError(f"Ambiguous match: {', '.join(substring_matches)}")
        return substring_matches[0]

    # Return original if no match found
    return collection

def _validate_philosopher_collection(collection: str) -> str:
    """
    Validate and normalize philosopher collection name.

    Args:
        collection: The collection name from the request

    Returns:
        Normalized collection name

    Raises:
        HTTPException: 400 if ambiguous, 404 if collection not found
    """
    if not collection or not collection.strip():
        available = ", ".join(_get_available_philosopher_collections())
        raise HTTPException(
            status_code=400,
            detail=f"Collection name is required. Available philosophers: {available}"
        )

    try:
        normalized = _normalize_collection_name(collection)
    except ValueError as e:
        # Ambiguous match - multiple philosophers matched
        available = ", ".join(_get_available_philosopher_collections())
        raise HTTPException(
            status_code=400,
            detail=f"Ambiguous collection name '{collection}': {str(e)}. Please be more specific. Available philosophers: {available}"
        )

    # Check if normalized name is in available philosophers
    if normalized not in _get_available_philosopher_collections():
        available = ", ".join(_get_available_philosopher_collections())
        raise HTTPException(
            status_code=404,
            detail=f"Philosopher '{collection}' not found. Available philosophers: {available}"
        )

    return normalized


def is_chat_history_enabled() -> bool:
    """Check if chat history feature is enabled in configuration."""
    settings = get_settings()
    return settings.chat_history


async def store_chat_message_safely(
    chat_history_service: ChatHistoryServiceDep,
    chat_qdrant_service: ChatQdrantServiceDep,
    session_id: Optional[str],
    role: str,
    content: str,
    philosopher_collection: Optional[str] = None,
    username: Optional[str] = None,
) -> None:
    """
    Safely store a chat message with graceful degradation on failure.

    Args:
        chat_history_service: Chat history service instance
        chat_qdrant_service: Chat Qdrant service instance
        session_id: Session identifier (optional)
        role: Message role (user or assistant)
        content: Message content
        philosopher_collection: Optional philosopher collection context
        username: Optional user identifier for multi-user support
    """
    if not is_chat_history_enabled() or not session_id:
        return

    # Track username adoption metrics
    if username:
        chat_monitoring.record_counter("chat_username_provided", {"username": username})
        log.info(f"Chat message stored with username tracking for {username}")
    else:
        chat_monitoring.record_counter("chat_username_not_provided")

    try:
        # Store message in PostgreSQL
        message = await chat_history_service.store_message(
            session_id=session_id,
            role=role,
            content=content,
            philosopher_collection=philosopher_collection,
            username=username,
        )

        # Upload to Qdrant for semantic search (non-blocking)
        try:
            point_ids = await chat_qdrant_service.upload_message_to_qdrant(message)

            # Update message with first point ID for reference
            if point_ids:
                await chat_history_service.update_message_qdrant_id(
                    message.message_id, point_ids[0]
                )

            log.info(
                f"Successfully stored and uploaded chat message for session {session_id}"
            )

        except Exception as qdrant_error:
            # Log Qdrant error but don't fail the request
            log.warning(
                f"Failed to upload message to Qdrant (continuing): {qdrant_error}"
            )

    except Exception as storage_error:
        # Log storage error but don't fail the request
        log.warning(f"Failed to store chat message (continuing): {storage_error}")


async def merge_conversation_history(
    chat_history_service: ChatHistoryServiceDep,
    session_id: Optional[str],
    provided_history: Optional[List[Any]],
    context_window_limit: int = CHAT_CONTEXT_WINDOW_CHARS,
) -> List[Any]:
    """
    Merge provided conversation history with stored chat history.

    Args:
        chat_history_service: Chat history service instance
        session_id: Session identifier for retrieving stored history
        provided_history: Conversation history provided in the request
        context_window_limit: Character limit for conversation context

    Returns:
        Merged conversation history optimized for context window
    """
    # Start with provided history if available
    merged_history = provided_history or []

    # If chat history is disabled or no session, return provided history
    if not is_chat_history_enabled() or not session_id:
        return merged_history

    try:
        # Calculate current context usage
        current_context_size = sum(
            len(msg.text) if hasattr(msg, "text") else 0 for msg in merged_history
        )

        # If we're already at the limit, return provided history
        if current_context_size >= context_window_limit:
            log.info(
                f"Provided history already at context limit ({current_context_size} chars)"
            )
            return merged_history

        # Retrieve stored conversation history
        remaining_context = context_window_limit - current_context_size

        # Estimate how many messages we can retrieve using average message length
        # Use a minimum of 10 messages as a reasonable floor
        min_message_limit = MAX_CONVERSATION_HISTORY_MESSAGES // 5  # 10 messages (50/5)
        estimated_message_limit = max(min_message_limit, remaining_context // AVERAGE_MESSAGE_LENGTH_CHARS)

        stored_messages = await chat_history_service.get_conversation_history(
            session_id=session_id, limit=estimated_message_limit, offset=0
        )

        if not stored_messages:
            log.info(f"No stored conversation history found for session {session_id}")
            return merged_history

        # Convert stored messages to ConversationMessage format
        from app.core.models import ConversationMessage

        stored_conversation = []
        context_used = current_context_size

        # Add stored messages in reverse chronological order (most recent first)
        # but we want them in chronological order for conversation flow
        for message in reversed(stored_messages):
            # Check if adding this message would exceed context limit
            message_size = len(message.content)
            if context_used + message_size > context_window_limit:
                break

            # Skip if this message is already in provided history
            # (to avoid duplication if user provided recent messages)
            if any(
                msg.text == message.content
                for msg in merged_history
                if hasattr(msg, "text")
            ):
                continue

            conversation_msg = ConversationMessage(
                id=message.message_id, role=message.role.value, text=message.content
            )

            stored_conversation.append(conversation_msg)
            context_used += message_size

        # Merge: stored history first (chronological), then provided history
        merged_history = stored_conversation + merged_history

        log.info(
            f"Merged conversation history: {len(stored_conversation)} stored + "
            f"{len(provided_history or [])} provided = {len(merged_history)} total messages "
            f"({context_used} chars)"
        )

        return merged_history

    except Exception as e:
        log.warning(f"Failed to merge conversation history (using provided only): {e}")
        return provided_history or []


async def search_user_documents(
    username: str,
    query_str: str,
    qdrant_manager: QdrantManagerDep,
    llm_manager: LLMManagerDep,
    limit: int = DEFAULT_PDF_CONTEXT_LIMIT,
) -> List[Any]:
    """
    Search user's document collection and return raw Qdrant results.

    This is a low-level helper used by both retrieve_user_document_context()
    and the PDF context integration in ask_philosophy endpoint.

    Args:
        username: Username to search documents for
        query_str: Query string to search against
        qdrant_manager: Qdrant manager instance
        llm_manager: LLM manager for embeddings
        limit: Maximum number of document chunks to retrieve

    Returns:
        List of ScoredPoint objects from Qdrant, or empty list on error
    """
    # Check if user has documents collection using centralized helper
    result = await check_collection_exists(
        qdrant_manager.qclient,
        username,
        f"[search_user_documents user={username}] "
    )

    if result in (CollectionCheckResult.NOT_FOUND, CollectionCheckResult.CONNECTION_ERROR):
        # Fail gracefully for search - no documents to search or connectivity issue
        log.warning(f"Document search unavailable for {username}: {result.value}")
        return []

    try:
        # Generate query embedding
        query_embedding = await llm_manager.get_embedding(query_str)

        # Search user's document collection
        search_result = await qdrant_manager.qclient.search(
            collection_name=username,
            query_vector=query_embedding,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return search_result if search_result else []

    except (ConnectionError, TimeoutError) as e:
        # Infrastructure failure during search operation
        log.error(
            f"Qdrant connectivity failure during document search for {username}: {e}",
            exc_info=True,
            extra={"username": username, "error_type": type(e).__name__}
        )
        return []  # Fail gracefully for optional feature
    except Exception as e:
        # Search operation failure (e.g., embedding generation failed)
        log.warning(
            f"Document search failed for {username}: {e}",
            extra={"username": username, "error_type": type(e).__name__}
        )
        return []


async def retrieve_user_document_context(
    username: str,
    query_str: str,
    qdrant_manager: QdrantManagerDep,
    llm_manager: LLMManagerDep,
    limit: int = 5,
) -> List[ConversationMessage]:
    """
    Retrieve relevant context from user's uploaded documents.

    Args:
        username: Username to search documents for
        query_str: Query string to search against
        qdrant_manager: Qdrant manager instance
        llm_manager: LLM manager for embeddings
        limit: Maximum number of document chunks to retrieve

    Returns:
        List of conversation messages with document context
    """
    # Use shared search helper
    search_result = await search_user_documents(
        username=username,
        query_str=query_str,
        qdrant_manager=qdrant_manager,
        llm_manager=llm_manager,
        limit=limit,
    )

    if not search_result:
        log.debug(f"No relevant documents found for user {username}")
        return []

    # Format document chunks as conversation context
    context_messages = []
    for idx, point in enumerate(search_result):
        if hasattr(point, "payload") and point.payload:
            text = point.payload.get("text", "")
            filename = point.payload.get("filename", "Unknown document")

            # Create context message
            context_msg = ConversationMessage(
                id=f"doc_context_{idx}",
                role="system",
                text=f"[From document: {filename}]\n{text}",
            )
            context_messages.append(context_msg)

    log.info(f"Retrieved {len(context_messages)} document chunks for user {username}")
    return context_messages


def calculate_required_context_window(
    nodes: List[Any], conversation_history: List[Any] = None, query_length: int = 0
) -> tuple[int, str]:
    """
    Calculate required context window based on actual content size.

    Args:
        nodes: Retrieved nodes with text content
        conversation_history: Previous conversation messages
        query_length: Length of current query in characters

    Returns:
        Tuple of (context_window_size, reasoning)
    """
    # Load context window settings from Pydantic Settings
    settings = get_settings()
    default_context = settings.default_context_window
    max_context = settings.max_context_window

    # Calculate total content length
    total_content_length = query_length

    # Add node content length
    for node in nodes:
        if hasattr(node, "payload") and isinstance(node.payload, dict):
            text = (
                node.payload.get("text", "")
                or node.payload.get("summary", "")
                or node.payload.get("conjecture", "")
            )
            total_content_length += len(text)

    # Add conversation history length
    if conversation_history:
        for msg in conversation_history:
            if hasattr(msg, "text"):
                total_content_length += len(msg.text)

    # Estimate tokens using configured character-to-token ratio
    estimated_tokens = total_content_length // CHARS_PER_TOKEN_ESTIMATE

    # Add buffer for system prompts and response
    estimated_tokens += CONTEXT_BUFFER_TOKENS

    # Determine appropriate context window
    if estimated_tokens <= default_context:
        context_window = default_context
        reasoning = f"Using default context ({estimated_tokens} estimated tokens < {default_context})"
    elif estimated_tokens <= max_context:
        # Round up to nearest 1024 for efficiency
        context_window = ((estimated_tokens + 1023) // 1024) * 1024
        # Clamp to max_context to prevent exceeding configured limit
        context_window = min(context_window, max_context)
        reasoning = f"Scaled context to {context_window} for {estimated_tokens} estimated tokens"
    else:
        context_window = max_context
        reasoning = f"Using max context ({estimated_tokens} estimated tokens > {max_context}, content will be truncated)"
        log.warning(
            f"Content size ({estimated_tokens} tokens) exceeds max context window ({max_context}). "
            f"Some content may be truncated."
        )

    return context_window, reasoning


@router.get("/ask")
@limiter.limit(get_default_limit)
@http_error_guard
async def ask_the_base_model_a_question(
    request: Request,
    query_str: Annotated[str, Query()],
    llm_manager: LLMManagerDep,
    cache_service: CacheServiceDep,
    subscription_manager: SubscriptionManagerDep,
    current_user: Optional[User] = Depends(get_optional_user_with_logging),
    temperature: Annotated[float, Query(gt=0, lt=1)] = 0.30,
    timeout: Annotated[int, Query(ge=5, le=180)] = 90,
):
    if not query_str or not query_str.strip():
        error = create_validation_error(
            field="query_str",
            message="Query string cannot be empty",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(current_user, subscription_manager, "/ask", request)

    # Create cache key for this query using SHA-256 (more secure than MD5)
    import hashlib
    cache_key = f"llm_query:{hashlib.sha256(f'{query_str}_{temperature}'.encode()).hexdigest()}"

    # Check cache using proper cache service with TTL
    if cache_service:
        cached_response = await cache_service.get(cache_key, cache_type='query')
        if cached_response:
            log.info(f"Returning cached response for query: {query_str[:50]}...")
            return cached_response

    try:
        response = await llm_manager.aquery(
            query_str,
            temperature=temperature,
            timeout=timeout
        )
        content = LLMResponseProcessor.extract_content(response)

        # Update usage tracking if payments enabled and user authenticated
        await track_subscription_usage(current_user, subscription_manager, "/ask", content)

        # Cache the response with configured TTL
        if cache_service:
            await cache_service.set(cache_key, content, ttl=LLM_QUERY_CACHE_TTL, cache_type='query')

        return content

    except LLMTimeoutError:
        error = create_timeout_error(
            timeout_seconds=timeout,
            operation="LLM query",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=408, detail=error.model_dump())


@router.get("/ask/stream")
@limiter.limit(get_streaming_limit)
@http_error_guard
async def ask_the_base_model_a_question_stream(
    request: Request,
    query_str: Annotated[str, Query()],
    llm_manager: LLMManagerDep,
    cache_service: CacheServiceDep,
    subscription_manager: SubscriptionManagerDep,
    current_user: Optional[User] = Depends(get_optional_user_with_logging),
    temperature: Annotated[float, Query(gt=0, lt=1)] = 0.30,
    timeout: Annotated[int, Query(ge=5, le=180)] = 90,
):
    """Stream LLM response for real-time text generation with caching support."""
    if not query_str or not query_str.strip():
        error = create_validation_error(
            field="query_str",
            message="Query string cannot be empty",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(current_user, subscription_manager, "/ask/stream", request)

    # Create cache key using SHA-256
    import hashlib
    cache_key = f"llm_stream:{hashlib.sha256(f'{query_str}_{temperature}'.encode()).hexdigest()}"

    # Check cache first - if found, stream the cached response
    if cache_service:
        cached_response = await cache_service.get(cache_key, cache_type='query')
        if cached_response:
            log.info(f"Streaming cached response for query: {query_str[:50]}...")

            async def stream_cached() -> AsyncGenerator[str, None]:
                """Stream cached response in chunks for consistent UX."""
                # Split cached response into reasonable chunks (simulate streaming)
                chunk_size = 50  # characters per chunk
                for i in range(0, len(cached_response), chunk_size):
                    chunk = cached_response[i:i + chunk_size]
                    data = json.dumps({"content": chunk, "done": False, "cached": True})
                    yield f"data: {data}\n\n"

                # Send completion signal
                final_data = json.dumps({"content": "", "done": True, "cached": True})
                yield f"data: {final_data}\n\n"

            return StreamingResponse(
                stream_cached(),
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

    async def generate_stream() -> AsyncGenerator[str, None]:
        request_id = getattr(request.state, 'request_id', None)
        full_response = ""  # Accumulate for caching
        try:
            async for chunk in llm_manager.aquery_stream(
                query_str,
                temperature=temperature,
                timeout=timeout
            ):
                # Format as Server-Sent Events (SSE)
                content = LLMResponseProcessor.extract_content(chunk)
                if content:
                    full_response += content
                    # Send as JSON for easier client parsing
                    data = json.dumps({"content": content, "done": False})
                    yield f"data: {data}\n\n"

            # Update usage tracking if payments enabled and user authenticated
            await track_subscription_usage(current_user, subscription_manager, "/ask/stream", full_response)

            # Cache the complete response for future requests
            if cache_service and full_response:
                await cache_service.set(cache_key, full_response, ttl=LLM_QUERY_CACHE_TTL, cache_type='query')
                log.info(f"Cached streaming response for query: {query_str[:50]}...")

            # Send completion signal
            final_data = json.dumps({"content": "", "done": True})
            yield f"data: {final_data}\n\n"

        except LLMTimeoutError:
            error = create_timeout_error(
                timeout_seconds=timeout,
                operation="LLM streaming query",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except LLMUnavailableError:
            error = create_service_unavailable_error(
                service="AI service",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except LLMError as e:
            error = create_internal_error(
                message=f"LLM processing failed: {str(e)}",
                error_type="llm_error",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except Exception as e:
            log.error(f"Unexpected error in /ask/stream: {e}", exc_info=True)
            error = create_internal_error(
                message="Unexpected error during streaming",
                error_type="unexpected_error",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


# @router.post("/talk_to_a_philosopher")
# async def converse_with_a_philosopher(request: AskPhilosopherRequest):
#     pass


@router.get("/get_philosophers")
@limiter.limit(get_default_limit)
async def get_available_philosophers(
    request: Request,
    qdrant_manager: QdrantManagerDep,
    cache_service: CacheServiceDep,
) -> List[str]:
    try:
        # Try cache first (warmed during startup)
        if cache_service:
            cache_key = cache_service.make_constant_cache_key(CACHE_KEY_PHILOSOPHER_COLLECTIONS)
            cached_philosophers = await cache_service.get(cache_key, cache_type='query')
            if cached_philosophers is not None:
                log.debug("Returning cached philosopher collections")
                return cached_philosophers

        # Cache miss - fetch from Qdrant
        philosophers = await qdrant_manager.get_collections()
        collection_names = [c.name for c in philosophers.collections]

        # Filter to philosopher collections using shared utility
        # CRITICAL: This MUST use the same filtering logic as cache warming
        # to ensure cached data matches what this endpoint produces
        available_philosophers = filter_philosopher_collections(collection_names)

        # Cache the result for subsequent requests
        if cache_service:
            cache_key = cache_service.make_constant_cache_key(CACHE_KEY_PHILOSOPHER_COLLECTIONS)
            await cache_service.set(
                cache_key,
                available_philosophers,
                ttl=PHILOSOPHER_COLLECTIONS_CACHE_TTL,
                cache_type='query'
            )

        log.info(f"Available philosophers: {available_philosophers}")
        return available_philosophers

    except LLMTimeoutError as e:
        log.warning(f"Get philosophers timed out: {e}")
        raise HTTPException(status_code=504, detail="Service temporarily unavailable")
    except LLMUnavailableError as e:
        log.error(f"Qdrant service unavailable: {e}")
        raise HTTPException(
            status_code=503, detail="Knowledge base temporarily unavailable"
        )
    except ConnectionError as e:
        log.error(f"Qdrant connection error: {e}")
        raise HTTPException(
            status_code=503, detail="Knowledge base temporarily unavailable"
        )
    except Exception as e:
        log.error(
            f"Failed to get philosophers unexpectedly: {e}. "
            f"Request from: {request.client.host if request.client else 'unknown'}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/ask_philosophy")
@limiter.limit(get_heavy_limit)
async def ask_a_philosophy_question(
    request: Request,
    body: HybridQueryRequest,
    qdrant_manager: QdrantManagerDep,
    llm_manager: LLMManagerDep,
    chat_history_service: ChatHistoryServiceDep,
    chat_qdrant_service: ChatQdrantServiceDep,
    subscription_manager: SubscriptionManagerDep,
    refeed: bool = Query(
        True,
        description="If true, the text content of meta_nodes is used to refine and retrieve more specific nodes from sub-collection.",
    ),
    immersive: bool = Query(
        False,
        description="If true, the LLM will respond from the perspective of the philosopher, using their style and knowledge.",
    ),
    temperature: float = Query(0.3, gt=0, lt=1),
    prompt_type: str | None = Query(
        None,
        description="Optional prompt style override: adaptive | writer_academic | reviewer",
    ),
    session_id: Optional[str] = Query(
        None, description="Optional session ID for chat history tracking"
    ),
    include_pdf_context: bool = Query(
        False,
        description="If true, search authenticated user's uploaded documents for relevant context. Requires JWT authentication.",
    ),
    user: Optional[User] = Depends(get_optional_user_with_logging),  # Optional JWT auth
) -> AskPhilosophyResponse:
    log.debug(f"Processing request from {request.client.host} within rate limit")

    # Validate and normalize collection name early
    try:
        normalized_collection = _validate_philosopher_collection(body.collection)
        # Update the body with normalized collection name
        body.collection = normalized_collection
        log.info(f"Collection validated and normalized: '{body.collection}'")
    except HTTPException:
        # Re-raise validation errors as-is
        raise

    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(user, subscription_manager, "/ask_philosophy", request)

    settings = get_settings()

    auth_header = request.headers.get("authorization")
    if auth_header:
        header_preview = auth_header[:20]
        if len(auth_header) > 20:
            header_preview = f"{header_preview}..."
        header_prefix = auth_header.split()[0] if " " in auth_header else "token"
        log.debug(
            "Authorization header detected for /ask_philosophy: prefix=%s preview=%s",
            header_prefix,
            header_preview,
        )
    else:
        log.debug("No Authorization header provided for /ask_philosophy request")

    # Extract username from authenticated user if available
    username: Optional[str] = None
    if user is not None:
        username = get_username_from_user(user)
        log.info(
            "Authenticated user resolved for /ask_philosophy: id=%s username=%s",
            getattr(user, "id", "unknown"),
            username,
        )
    else:
        log.warning(
            "Optional authentication returned no user for /ask_philosophy; token missing, invalid, or expired"
        )

    log.debug(
        "JWT auth result for /ask_philosophy: user_present=%s include_pdf_context=%s",
        user is not None,
        include_pdf_context,
    )

    log.debug(
        "PDF context gate: include_pdf_context=%s user_present=%s feature_enabled=%s",
        include_pdf_context,
        user is not None,
        settings.chat_use_pdf_context,
    )

    # Validate that PDF context requires authentication and matches JWT user
    if include_pdf_context:
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required for PDF context. Please provide a valid JWT token via Authorization header."
            )
        # Defensive check: Verify username was properly extracted from authenticated user
        if not username:
            log.error("PDF context requested but username extraction failed for authenticated user")
            raise HTTPException(
                status_code=500,
                detail="Failed to extract username from authentication token"
            )

    try:
        # Store user query if chat history is enabled
        await store_chat_message_safely(
            chat_history_service=chat_history_service,
            chat_qdrant_service=chat_qdrant_service,
            session_id=session_id,
            role="user",
            content=body.query_str,
            philosopher_collection=body.collection,
            username=username,
        )

        # Gather philosopher collection nodes
        philosopher_nodes = await qdrant_manager.gather_points_and_sort(
            body, refeed=refeed
        )

        if not philosopher_nodes:
            raise HTTPException(
                status_code=404,
                detail="No relevant context found for the requested collection",
            )

        # Optionally retrieve and merge user document context
        nodes = philosopher_nodes  # Default to philosopher nodes only

        if username and include_pdf_context and settings.chat_use_pdf_context:
            log.info("Retrieving document context for user %s", username)

            # Record PDF context request metric
            chat_monitoring.record_counter(
                "pdf_context_requests",
                {"username": username, "collection": body.collection},
            )

            try:
                # Track document search duration
                doc_search_start = time.time()

                log.debug(
                    "Initiating PDF context search: username=%s query_length=%s limit=%s",
                    username,
                    len(body.query_str),
                    settings.pdf_context_limit,
                )

                # Use shared search helper to avoid code duplication
                doc_results = await search_user_documents(
                    username=username,
                    query_str=body.query_str,
                    qdrant_manager=qdrant_manager,
                    llm_manager=llm_manager,
                    limit=settings.pdf_context_limit,
                )

                doc_search_duration_ms = (time.time() - doc_search_start) * 1000

                # Record search duration
                chat_monitoring.record_timer_ms(
                    "pdf_context_search_duration_ms",
                    doc_search_duration_ms,
                    {"username": username},
                )

                result_count = len(doc_results) if doc_results else 0
                log.debug(
                    "PDF context search completed: username=%s results=%s duration_ms=%.2f",
                    username,
                    result_count,
                    doc_search_duration_ms,
                )

                if doc_results:
                    # Enhance document results with source attribution
                    # doc_results are already ScoredPoint objects from Qdrant - just mark them as user documents
                    doc_nodes = []
                    for result in doc_results:
                        if hasattr(result, "payload") and result.payload:
                            # Add source marker to existing payload for attribution
                            result.payload["source"] = "user_document"
                            doc_nodes.append(result)

                    if doc_nodes:
                        # Merge document nodes with philosopher nodes
                        # Prioritize document context by placing it first
                        nodes = doc_nodes + philosopher_nodes

                        # Record successful document context retrieval
                        chat_monitoring.record_histogram(
                            "pdf_context_documents_found",
                            len(doc_nodes),
                            {"username": username},
                        )
                        chat_monitoring.record_counter(
                            "pdf_context_success",
                            {"username": username},
                        )

                        log.info(
                            "Merged %s document chunks with %s philosopher nodes for user %s",
                            len(doc_nodes),
                            len(philosopher_nodes),
                            username,
                        )
                else:
                    log.debug("No relevant documents found for user %s", username)
                    # Record no documents found
                    chat_monitoring.record_counter(
                        "pdf_context_no_documents",
                        {"username": username},
                    )

            except Exception as e:
                # Gracefully handle errors - continue with philosopher nodes only
                log.warning("Could not retrieve document context for %s: %s", username, e)
                # Record document context error - use safe_record_metric to prevent monitoring failures from breaking graceful degradation
                safe_record_metric(
                    "pdf_context_errors",
                    metric_type="counter",
                    labels={"username": username, "error_type": type(e).__name__}
                )
                nodes = philosopher_nodes

        # Merge provided conversation history with stored chat history
        conversation_history = await merge_conversation_history(
            chat_history_service=chat_history_service,
            session_id=session_id,
            provided_history=body.conversation_history,
            context_window_limit=CHAT_CONTEXT_WINDOW_CHARS,  # Reserve space for conversation context
        )

        # Calculate required context window based on actual content
        context_window, reasoning = calculate_required_context_window(
            nodes=nodes,
            conversation_history=conversation_history,
            query_length=len(body.query_str),
        )

        # Log context window decision with metrics
        log.info(
            f"Context window decision for /ask_philosophy: {reasoning} | "
            f"Nodes: {len(nodes)}, Query length: {len(body.query_str)}, "
            f"History messages: {len(conversation_history)}, "
            f"Chosen context: {context_window} tokens"
        )

        llm_manager.set_llm_context_window(context_window)
        immersive_mode = body.collection if immersive else None

        response = await llm_manager.achat(
            body.query_str,
            nodes,
            conversation_history=conversation_history,
            immersive_mode=immersive_mode,
            temperature=temperature,
            prompt_type=prompt_type,
        )

        processed_response_text = (
            LLMResponseProcessor.extract_content_with_think_tag_removal(response)
        )

        # Update usage tracking if payments enabled and user authenticated
        await track_subscription_usage(user, subscription_manager, "/ask_philosophy", processed_response_text)

        # Store AI response if chat history is enabled
        await store_chat_message_safely(
            chat_history_service=chat_history_service,
            chat_qdrant_service=chat_qdrant_service,
            session_id=session_id,
            role="assistant",
            content=processed_response_text,
            philosopher_collection=body.collection,
            username=username,
        )

        processed_response = AskPhilosophyResponse(
            text=processed_response_text, raw=response.raw
        )

        return processed_response

    except HTTPException:
        raise
    except LLMTimeoutError as e:
        log.warning(f"Philosophy question timed out: {e}")
        raise HTTPException(status_code=504, detail="Response generation timed out")
    except LLMUnavailableError as e:
        log.error(f"LLM service unavailable for philosophy question: {e}")
        raise HTTPException(
            status_code=503, detail="AI service temporarily unavailable"
        )
    except LLMResponseError as e:
        log.warning(f"Invalid LLM response for philosophy question: {e}")
        raise HTTPException(status_code=502, detail="Invalid AI response received")
    except LLMError as e:
        # Check if this is actually a Qdrant collection error disguised as LLM error
        error_msg = str(e).lower()
        if "collection" in error_msg and ("doesn't exist" in error_msg or "not found" in error_msg):
            log.warning(f"Collection not found for philosophy question: {e}")
            raise HTTPException(
                status_code=404, 
                detail=f"Knowledge collection '{body.collection}' not found. Available philosophers: {', '.join(_get_available_philosopher_collections())}"
            )
        log.warning(f"LLM error during philosophy question: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate response")
    except ConnectionError as e:
        log.error(f"Qdrant connection failed: {e}")
        raise HTTPException(
            status_code=503, detail="Knowledge base temporarily unavailable"
        )
    except Exception as e:
        log.error(
            f"Philosophy question failed unexpectedly: {e}. "
            f"Collection: {body.collection}, "
            f"Query: {body.query_str[:100]}{'...' if len(body.query_str) > 100 else ''}, "
            f"Refeed: {refeed}, Immersive: {immersive}, Temperature: {temperature}, "
            f"Prompt type: {prompt_type}, "
            f"Context window: {context_window if 'context_window' in locals() else 'not set'}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        llm_manager.set_llm_context_window()


@router.post("/ask_philosophy/stream")
@limiter.limit(get_streaming_limit)
async def ask_a_philosophy_question_stream(
    request: Request,
    body: HybridQueryRequest,
    qdrant_manager: QdrantManagerDep,
    llm_manager: LLMManagerDep,
    chat_history_service: ChatHistoryServiceDep,
    chat_qdrant_service: ChatQdrantServiceDep,
    subscription_manager: SubscriptionManagerDep,
    refeed: bool = Query(
        True,
        description="If true, the text content of meta_nodes is used to refine and retrieve more specific nodes from sub-collection.",
    ),
    immersive: bool = Query(
        False,
        description="If true, the LLM will respond from the perspective of the philosopher, using their style and knowledge.",
    ),
    temperature: float = Query(0.3, gt=0, lt=1),
    prompt_type: str | None = Query(
        None,
        description="Optional prompt style override: adaptive | writer_academic | reviewer",
    ),
    session_id: Optional[str] = Query(
        None, description="Optional session ID for chat history tracking"
    ),
    include_pdf_context: bool = Query(
        False,
        description="If true, search authenticated user's uploaded documents for relevant context. Requires JWT authentication.",
    ),
    user: Optional[User] = Depends(get_optional_user_with_logging),  # Optional JWT auth
):
    """Stream philosophy question response for real-time text generation."""
    log.debug(f"Processing streaming request from {request.client.host} within rate limit")

    # Validate and normalize collection name early for streaming
    try:
        normalized_collection = _validate_philosopher_collection(body.collection)
        # Update the body with normalized collection name
        body.collection = normalized_collection
        log.info(f"Stream: Collection validated and normalized: '{body.collection}'")
    except HTTPException as e:
        # Convert validation errors to streaming format
        request_id = getattr(request.state, 'request_id', None)

        async def error_stream():
            error_data = json.dumps({
                "error": {
                    "type": "validation_error",
                    "message": str(e.detail),
                    "status_code": e.status_code,
                    "request_id": request_id
                },
                "done": True
            })
            yield f"data: {error_data}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    # Extract username from authenticated user if available
    username: Optional[str] = None
    if user is not None:
        username = get_username_from_user(user)
        log.info(
            "Authenticated user resolved for /ask_philosophy/stream: id=%s username=%s",
            getattr(user, "id", "unknown"),
            username,
        )

    # Subscription check: Enforce access control if payments are enabled
        # (Moved subscription check into generator)

    settings = get_settings()

    # Validate that PDF context requires authentication and matches JWT user
    if include_pdf_context:
        if user is None:
            error = create_authentication_error(
                message="Authentication required for PDF context. Please provide a valid JWT token via Authorization header.",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=401, detail=error.model_dump())
        # Defensive check: Verify username was properly extracted from authenticated user
        if not username:
            log.error("PDF context (streaming) requested but username extraction failed for authenticated user")
            error = create_internal_error(
                message="Failed to extract username from authentication token",
                error_type="authentication_processing_error",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=500, detail=error.model_dump())

    async def generate_philosophy_stream() -> AsyncGenerator[str, None]:
        try:
            # Subscription check inside generator for proper SSE error handling
            await check_subscription_access(user, subscription_manager, "/ask_philosophy/stream", request)
            # Store user query if chat history is enabled
            await store_chat_message_safely(
                chat_history_service=chat_history_service,
                chat_qdrant_service=chat_qdrant_service,
                session_id=session_id,
                role="user",
                content=body.query_str,
                philosopher_collection=body.collection,
                username=username,
            )
        except HTTPException as e:
            # SSE error formatting for subscription/authorization errors
            error_data = json.dumps({"error": str(e.detail), "done": True})
            yield f"data: {error_data}\n\n"
            return

            # Gather philosopher collection nodes
            philosopher_nodes = await qdrant_manager.gather_points_and_sort(
                body, refeed=refeed
            )

            if not philosopher_nodes:
                request_id = getattr(request.state, 'request_id', None)
                error = create_not_found_error(
                    resource="relevant context",
                    identifier=body.collection,
                    request_id=request_id
                )
                error_data = json.dumps({"error": error.model_dump(), "done": True})
                yield f"data: {error_data}\n\n"

            # Optionally retrieve and merge user document context
            nodes = philosopher_nodes  # Default to philosopher nodes only

            if username and include_pdf_context and settings.chat_use_pdf_context:
                log.info("Retrieving document context for user %s", username)
                try:
                    doc_results = await search_user_documents(
                        username=username,
                        query_str=body.query_str,
                        qdrant_manager=qdrant_manager,
                        llm_manager=llm_manager,
                        limit=settings.pdf_context_limit,
                    )

                    if doc_results:
                        doc_nodes = []
                        for result in doc_results:
                            if hasattr(result, "payload") and result.payload:
                                result.payload["source"] = "user_document"
                                doc_nodes.append(result)

                        if doc_nodes:
                            nodes = doc_nodes + philosopher_nodes
                            log.info(
                                "Merged %s document chunks with %s philosopher nodes for user %s",
                                len(doc_nodes),
                                len(philosopher_nodes),
                                username,
                            )
                except Exception as e:
                    log.warning("Could not retrieve document context for %s: %s", username, e)
                    nodes = philosopher_nodes

            # Merge provided conversation history with stored chat history
            conversation_history = await merge_conversation_history(
                chat_history_service=chat_history_service,
                session_id=session_id,
                provided_history=body.conversation_history,
                context_window_limit=CHAT_CONTEXT_WINDOW_CHARS,
            )

            # Calculate required context window
            context_window, reasoning = calculate_required_context_window(
                nodes=nodes,
                conversation_history=conversation_history,
                query_length=len(body.query_str),
            )

            log.info(
                f"Context window decision for /ask_philosophy/stream: {reasoning} | "
                f"Nodes: {len(nodes)}, Query length: {len(body.query_str)}, "
                f"History messages: {len(conversation_history)}, "
                f"Chosen context: {context_window} tokens"
            )

            llm_manager.set_llm_context_window(context_window)
            immersive_mode = body.collection if immersive else None

            # Stream the response
            full_response = ""
            async for chunk in llm_manager.achat_stream(
                body.query_str,
                nodes,
                conversation_history=conversation_history,
                immersive_mode=immersive_mode,
                temperature=temperature,
                prompt_type=prompt_type,
            ):
                content = LLMResponseProcessor.extract_content(chunk)
                if content:
                    full_response += content
                    # Send chunk as JSON for easier client parsing
                    data = json.dumps({"content": content, "done": False})
                    yield f"data: {data}\n\n"

            # Process the full response and store it
            # Create a mock response object for processing
            class MockResponse:
                def __init__(self, text: str) -> None:
                    self.text = text
                    self.raw = {"content": text}

            mock_response = MockResponse(full_response)
            processed_response_text = (
                LLMResponseProcessor.extract_content_with_think_tag_removal(mock_response)
            )

            # Update usage tracking if payments enabled and user authenticated
            await track_subscription_usage(user, subscription_manager, "/ask_philosophy/stream", processed_response_text)

            # Store AI response if chat history is enabled
            await store_chat_message_safely(
                chat_history_service=chat_history_service,
                chat_qdrant_service=chat_qdrant_service,
                session_id=session_id,
                role="assistant",
                content=processed_response_text,
                philosopher_collection=body.collection,
                username=username,
            )

            # Send completion signal
            final_data = json.dumps({"content": "", "done": True})
            yield f"data: {final_data}\n\n"

        except LLMTimeoutError as e:
            log.warning(f"Philosophy question stream timed out: {e}")
            request_id = getattr(request.state, 'request_id', None)
            error = create_timeout_error(
                timeout_seconds=context_window if 'context_window' in locals() else 120,
                operation="philosophy question streaming",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except LLMUnavailableError as e:
            log.error(f"LLM unavailable for philosophy stream: {e}")
            request_id = getattr(request.state, 'request_id', None)
            error = create_service_unavailable_error(
                service="AI service",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except LLMResponseError as e:
            log.warning(f"Invalid LLM response in philosophy stream: {e}")
            request_id = getattr(request.state, 'request_id', None)
            error = create_invalid_response_error(
                service="AI service",
                message="Invalid response during streaming",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except LLMError as e:
            log.warning(f"LLM error during philosophy stream: {e}")
            request_id = getattr(request.state, 'request_id', None)
            error = create_internal_error(
                message=f"LLM processing failed: {str(e)}",
                error_type="llm_error",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except ConnectionError as e:
            log.error(f"Connection error in philosophy stream: {e}")
            request_id = getattr(request.state, 'request_id', None)
            error = create_service_unavailable_error(
                service="knowledge base",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        except Exception as e:
            log.error(f"Philosophy question stream failed: {e}", exc_info=True)
            request_id = getattr(request.state, 'request_id', None)
            error = create_internal_error(
                message="Unexpected error during streaming",
                error_type="unexpected_error",
                request_id=request_id
            )
            error_data = json.dumps({"error": error.model_dump(), "done": True})
            yield f"data: {error_data}\n\n"
        finally:
            llm_manager.set_llm_context_window()

    return StreamingResponse(
        generate_philosophy_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("/query_hybrid")
@limiter.limit(get_default_limit)
async def gather_points_from_collections(
    request: Request,
    body: HybridQueryRequest,
    qdrant_manager: QdrantManagerDep,
    llm_manager: LLMManagerDep,
    subscription_manager: SubscriptionManagerDep,
    current_user: Optional[User] = Depends(get_optional_user_with_logging),
    vet_mode: bool = Query(
        False,
        description="If true, the LLM will select the most relevant node IDs from the results and return them as a response. Mutually exclusive with raw_mode.",
    ),
    raw_mode: bool = Query(
        False,
        description="If true, nodes are returned in dict format with collection name as keys, and nodes along with the associated vector type as values. Mutually exclusive with vet_mode.",
    ),
    refeed: bool = Query(
        True,
        description="If true, meta_nodes are first retrieved and used to refine and retrieve more specific nodes from sub-collection (if available).",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Maximum number of nodes to return. Default is 10, maximum is 100.",
    ),
    temperature: float = Query(0.30, gt=0, lt=1),
):
    log.debug(f"Processing request from {request.client.host} within rate limit")

    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(current_user, subscription_manager, "/query_hybrid", request)

    # Validate and normalize collection name early for hybrid query
    try:
        normalized_collection = _validate_philosopher_collection(body.collection)
        # Update the body with normalized collection name
        body.collection = normalized_collection
        log.info(f"Hybrid query: Collection validated and normalized: '{body.collection}'")
    except HTTPException:
        # Re-raise validation errors as-is
        raise

    # Validate mutually exclusive modes
    if vet_mode and raw_mode:
        error = create_conflict_error(
            message="vet_mode and raw_mode are mutually exclusive",
            conflicting_params=["vet_mode", "raw_mode"],
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    try:
        nodes = await qdrant_manager.gather_points_and_sort(
            body, raw_mode=raw_mode, refeed=refeed, limit=limit
        )

        if not nodes:
            error = create_not_found_error(
                resource="query results",
                identifier=body.query_str[:50],
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        if not vet_mode or raw_mode:
            # Track subscription usage for raw mode (estimate based on node count)
            # Convert nodes to string representation for usage tracking
            if hasattr(nodes, '__iter__'):
                # Estimate content size based on number of nodes for tracking
                response_content = f"Query results: {len(list(nodes))} nodes returned"
            else:
                response_content = str(nodes)
            await track_subscription_usage(current_user, subscription_manager, "/query_hybrid", response_content)
            return nodes

        # Calculate required context window for vetting
        context_window, reasoning = calculate_required_context_window(
            nodes=nodes,
            conversation_history=None,  # No conversation history in vet mode
            query_length=len(body.query_str),
        )

        # Log context window decision with metrics
        log.info(
            f"Context window decision for /query_hybrid (vet mode): {reasoning} | "
            f"Nodes: {len(nodes)}, Query length: {len(body.query_str)}, "
            f"Chosen context: {context_window} tokens"
        )

        llm_manager.set_llm_context_window(context_window)
        response = await llm_manager.avet(
            body.query_str, nodes, temperature=temperature
        )

        # Track subscription usage for vet mode query
        response_text = LLMResponseProcessor.extract_content(response)
        await track_subscription_usage(current_user, subscription_manager, "/query_hybrid", response_text)

        return response

    except HTTPException:
        raise
    except LLMTimeoutError as e:
        log.warning(f"Hybrid query timed out: {e}")
        error = create_timeout_error(
            timeout_seconds=context_window if 'context_window' in locals() else 120,
            operation="hybrid query processing",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=504, detail=error.model_dump())
    except LLMUnavailableError as e:
        log.error(f"Service unavailable during hybrid query: {e}")
        error = create_service_unavailable_error(
            service="AI service",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=503, detail=error.model_dump())
    except LLMResponseError as e:
        log.warning(f"Invalid response during vetting: {e}")
        error = create_invalid_response_error(
            service="AI service",
            message="Invalid response received during query vetting",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=502, detail=error.model_dump())
    except LLMError as e:
        log.warning(f"LLM error during hybrid query: {e}")
        error = create_internal_error(
            message="Failed to process query",
            error_type="llm_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())
    except ConnectionError as e:
        log.error(f"Qdrant connection error during hybrid query: {e}")
        error = create_service_unavailable_error(
            service="knowledge base",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=503, detail=error.model_dump())
    except Exception as e:
        log.error(
            f"Hybrid query failed unexpectedly: {e}. "
            f"Collection: {body.collection}, "
            f"Query: {body.query_str[:100]}{'...' if len(body.query_str) > 100 else ''}, "
            f"Vet mode: {vet_mode}, Raw mode: {raw_mode}, Refeed: {refeed}, "
            f"Limit: {limit}, Temperature: {temperature}, "
            f"Context window: {context_window if 'context_window' in locals() else 'not set'}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        llm_manager.set_llm_context_window()
