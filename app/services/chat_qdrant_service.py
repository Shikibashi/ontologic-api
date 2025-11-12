"""
ChatQdrantService for managing chat history vector operations.

This service handles vector generation, storage, and search for chat messages
with environment-aware collection management and strict session isolation.
Enhanced with comprehensive error handling and graceful degradation.
"""

import os
import asyncio
import uuid
from typing import Dict, List, Any, Optional, Tuple, TYPE_CHECKING
from datetime import datetime

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException

from app.core.logger import log
from app.core.db_models import ChatMessage, MessageRole
from app.core.exceptions import LLMError, LLMTimeoutError, LLMUnavailableError
from app.core.chat_exceptions import (
    ChatVectorStoreError, ChatValidationError, ChatPrivacyError,
    ChatTimeoutError, ChatResourceError
)
from app.core.chat_error_handler import vector_store_fallback_decorator
from app.services.chat_monitoring import monitor_chat_operation, chat_monitoring
from app.services.llm_manager import LLMManager
from app.config.settings import get_settings

if TYPE_CHECKING:
    from app.services.expansion_service import ExpansionService


class ChatQdrantService:
    """
    Service for managing chat history vector operations with environment-aware collection management.

    Features:
    - Environment-specific collection names (Chat_History_Dev, Chat_History_Test, Chat_History)
    - Automatic collection initialization and validation
    - Message vector generation and upload with chunking support
    - Semantic search with strict session filtering
    - Privacy isolation between users

    LIFECYCLE: This service is lifespan-managed. It is initialized during
    application startup and stored in app.state. Access via dependency
    injection using get_chat_qdrant_service() from app.core.dependencies.

    Do not instantiate directly in request handlers. Use:
        async def my_endpoint(chat_qdrant: ChatQdrantServiceDep):
            # Use chat_qdrant here
    """

    def __init__(self, qdrant_client: AsyncQdrantClient, llm_manager: LLMManager,
                 expansion_service: Optional['ExpansionService'] = None):
        """
        Initialize ChatQdrantService with Qdrant client and LLM manager.

        NOTE: For lifespan-managed initialization, use the ChatQdrantService.start()
        classmethod instead of calling __init__ directly.

        Args:
            qdrant_client: Async Qdrant client instance
            llm_manager: LLM manager for vector generation
            expansion_service: Optional expansion service for fusion search
        """
        self.qclient = qdrant_client
        self.llm_manager = llm_manager
        self.expansion_service = expansion_service
        self.collection_name = self._get_environment_collection_name()
        self.timeout_seconds = 30
        self.retry_attempts = 3
        self.max_chunk_size = 1000  # Maximum characters per chunk for long messages

        # Load fusion configuration
        try:
            settings = get_settings()
            self.use_fusion = settings.use_fusion_search
            self.fusion_methods = [m.strip() for m in settings.fusion_methods.split(",")] if settings.fusion_methods else ["hyde", "rag_fusion"]
            self.fusion_rrf_k = settings.fusion_rrf_k
            self.fusion_max_queries = settings.fusion_max_queries

            if self.use_fusion and not self.expansion_service:
                log.warning("Fusion search enabled but ExpansionService not provided - fusion will be disabled")
                self.use_fusion = False

        except Exception as e:
            log.warning(f"Failed to load fusion configuration: {e} - fusion disabled")
            self.use_fusion = False
            self.fusion_methods = ["hyde", "rag_fusion"]
            self.fusion_rrf_k = 60
            self.fusion_max_queries = 4

    @classmethod
    async def start(
        cls,
        qdrant_client: AsyncQdrantClient,
        llm_manager: LLMManager,
        expansion_service: Optional['ExpansionService'] = None
    ):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            qdrant_client: Async Qdrant client instance
            llm_manager: LLM manager for vector generation
            expansion_service: Optional expansion service for fusion search

        Returns:
            Initialized ChatQdrantService instance
        """
        instance = cls(
            qdrant_client=qdrant_client,
            llm_manager=llm_manager,
            expansion_service=expansion_service
        )
        log.info("ChatQdrantService initialized for lifespan management")
        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        # Clean up any async resources if needed
        log.info("ChatQdrantService cleaned up")

    def _get_environment_collection_name(self) -> str:
        """
        Get environment-specific collection name for chat history.
        
        Returns:
            Environment-specific collection name:
            - Production: "Chat_History"
            - Development: "Chat_History_Dev" 
            - Testing: "Chat_History_Test"
        """
        app_env = os.environ.get("APP_ENV", "dev").lower()
        
        if app_env == "prod":
            return "Chat_History"
        elif app_env == "test":
            return "Chat_History_Test"
        else:
            return "Chat_History_Dev"

    @classmethod
    def get_all_chat_collection_patterns(cls) -> List[str]:
        """
        Get all possible chat collection name patterns for filtering.
        
        Returns:
            List of chat collection patterns to exclude from public APIs
        """
        return ["Chat_History", "Chat_History_Dev", "Chat_History_Test"]

    @classmethod
    def is_chat_collection(cls, collection_name: str) -> bool:
        """
        Check if a collection name is a chat history collection.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            True if the collection is a chat history collection
        """
        chat_patterns = cls.get_all_chat_collection_patterns()
        return collection_name in chat_patterns

    async def with_timeout(self, coro, timeout_seconds=None, operation_name="Chat Qdrant operation"):
        """Wrapper for Qdrant operations with timeout and comprehensive error handling."""
        timeout_seconds = timeout_seconds or self.timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            log.error(f"{operation_name} timed out after {timeout_seconds}s")
            raise ChatTimeoutError(
                message=f"{operation_name} timed out",
                operation=operation_name,
                timeout_seconds=timeout_seconds
            )
        except ResponseHandlingException as e:
            log.error(f"{operation_name} response handling failed: {e}")
            raise ChatVectorStoreError(
                message=f"Qdrant response handling error: {str(e)}",
                operation=operation_name,
                collection_name=self.collection_name,
                recoverable=True
            )
        except UnexpectedResponse as e:
            log.error(f"{operation_name} unexpected response: {e}")
            raise ChatVectorStoreError(
                message=f"Qdrant unexpected response: {str(e)}",
                operation=operation_name,
                collection_name=self.collection_name,
                recoverable=True
            )
        except ConnectionError as e:
            log.error(f"{operation_name} connection failed: {e}")
            raise ChatVectorStoreError(
                message=f"Qdrant connection error: {str(e)}",
                operation=operation_name,
                collection_name=self.collection_name,
                recoverable=True,
                fallback_available=True
            )
        except Exception as e:
            log.error(f"{operation_name} failed with unexpected error: {e}")
            raise ChatVectorStoreError(
                message=f"Qdrant operation failed: {str(e)}",
                operation=operation_name,
                collection_name=self.collection_name,
                details={"error_type": type(e).__name__}
            )

    async def execute_with_retries(self, operation, timeout_seconds=None, operation_name="Chat Qdrant operation"):
        """Execute an async operation with retry and comprehensive error handling."""
        attempts = self.retry_attempts
        last_error = None

        for attempt in range(1, attempts + 1):
            try:
                return await self.with_timeout(
                    operation(),
                    timeout_seconds=timeout_seconds,
                    operation_name=operation_name
                )
            except (ChatTimeoutError, ChatVectorStoreError) as exc:
                last_error = exc
                
                # Don't retry certain types of errors
                if isinstance(exc, ChatVectorStoreError) and not exc.recoverable:
                    log.error(f"{operation_name} failed with non-recoverable error")
                    raise
                
                if attempt >= attempts:
                    log.error(f"{operation_name} failed after {attempts} attempts")
                    raise
                
                backoff = min(2 ** (attempt - 1), 8)
                log.warning(
                    f"{operation_name} attempt {attempt} failed ({exc.message}). Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
            except Exception as e:
                # Convert unexpected errors to ChatVectorStoreError
                chat_error = ChatVectorStoreError(
                    message=f"Unexpected error in {operation_name}: {str(e)}",
                    operation=operation_name,
                    collection_name=self.collection_name,
                    details={"error_type": type(e).__name__}
                )
                last_error = chat_error
                
                if attempt >= attempts:
                    log.error(f"{operation_name} failed after {attempts} attempts with unexpected error")
                    raise chat_error
                
                backoff = min(2 ** (attempt - 1), 8)
                log.warning(
                    f"{operation_name} attempt {attempt} failed with unexpected error. Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)

        if last_error:
            raise last_error

    async def ensure_chat_collection_exists(self) -> None:
        """
        Ensure the chat history collection exists with proper configuration.
        
        Creates the collection if it doesn't exist with appropriate vector configuration
        for dense embeddings and metadata structure for chat messages.
        """
        try:
            # Check if collection already exists
            collections = await self.execute_with_retries(
                lambda: self.qclient.get_collections(),
                operation_name=f"Check if collection {self.collection_name} exists"
            )
            
            existing_collections = [col.name for col in collections.collections]
            
            if self.collection_name in existing_collections:
                log.info(f"Chat collection {self.collection_name} already exists")
                return

            # Create collection with dense vector configuration
            log.info(f"Creating chat collection: {self.collection_name}")
            
            await self.execute_with_retries(
                lambda: self.qclient.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=4096,  # Size for Salesforce/sfr-embedding-mistral model
                        distance=models.Distance.COSINE
                    )
                ),
                operation_name=f"Create chat collection {self.collection_name}"
            )
            
            log.info(f"Successfully created chat collection: {self.collection_name}")
            
        except Exception as e:
            log.error(f"Failed to ensure chat collection exists: {e}")
            raise LLMError(f"Failed to initialize chat collection: {str(e)}")

    async def validate_collection_configuration(self) -> bool:
        """
        Validate that the chat collection has the correct configuration.
        
        Returns:
            True if collection configuration is valid
            
        Raises:
            LLMError: If collection configuration is invalid
        """
        try:
            collection_info = await self.execute_with_retries(
                lambda: self.qclient.get_collection(self.collection_name),
                operation_name=f"Get collection info for {self.collection_name}"
            )
            
            # Validate vector configuration
            vectors_config = collection_info.config.params.vectors
            if vectors_config.size != 4096:
                raise LLMError(f"Invalid vector size: expected 4096, got {vectors_config.size}")
            
            if vectors_config.distance != models.Distance.COSINE:
                raise LLMError(f"Invalid distance metric: expected COSINE, got {vectors_config.distance}")
            
            log.info(f"Chat collection {self.collection_name} configuration validated successfully")
            return True
            
        except Exception as e:
            log.error(f"Collection validation failed: {e}")
            raise LLMError(f"Chat collection validation failed: {str(e)}")

    def _chunk_message_content(self, content: str) -> List[Tuple[str, int, int]]:
        """
        Split long message content into chunks for vector generation.
        
        Args:
            content: Message content to chunk
            
        Returns:
            List of tuples (chunk_text, chunk_index, total_chunks)
        """
        if len(content) <= self.max_chunk_size:
            return [(content, 0, 1)]
        
        chunks = []
        chunk_index = 0
        
        # Split by sentences first, then by character limit if needed
        sentences = content.split('. ')
        current_chunk = ""
        
        for sentence in sentences:
            # If adding this sentence would exceed limit, save current chunk
            if len(current_chunk) + len(sentence) + 2 > self.max_chunk_size and current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "
            else:
                current_chunk += sentence + ". "
        
        # Add the last chunk if it has content
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        # If we still have chunks that are too long, split by character limit
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= self.max_chunk_size:
                final_chunks.append(chunk)
            else:
                # Split by character limit as last resort
                for i in range(0, len(chunk), self.max_chunk_size):
                    final_chunks.append(chunk[i:i + self.max_chunk_size])
        
        total_chunks = len(final_chunks)
        return [(chunk, idx, total_chunks) for idx, chunk in enumerate(final_chunks)]

    async def generate_message_vector(self, content: str) -> List[float]:
        """
        Generate dense vector embedding for message content.
        
        Args:
            content: Message content to vectorize
            
        Returns:
            Dense vector embedding as list of floats
            
        Raises:
            LLMError: If vector generation fails
        """
        if not content or not content.strip():
            raise LLMError("Message content cannot be empty for vector generation")
        
        try:
            log.debug(f"Generating vector for message content (length: {len(content)})")
            vector = await self.llm_manager.generate_dense_vector(content)
            
            if not vector or len(vector) != 4096:
                raise LLMError(f"Invalid vector generated: expected 4096 dimensions, got {len(vector) if vector else 0}")
            
            return vector
            
        except Exception as e:
            log.error(f"Failed to generate message vector: {e}")
            raise LLMError(f"Message vector generation failed: {str(e)}")

    @monitor_chat_operation("upload_message_to_qdrant")
    @vector_store_fallback_decorator()
    async def upload_message_to_qdrant(self, message: ChatMessage) -> List[str]:
        """
        Upload chat message to Qdrant with vector generation, chunking support, and error handling.
        
        Args:
            message: ChatMessage instance to upload
            
        Returns:
            List of Qdrant point IDs for the uploaded message chunks
            
        Raises:
            ChatValidationError: If message validation fails
            ChatVectorStoreError: If upload fails
            ChatResourceError: If resource limits are exceeded
        """
        # Input validation
        if not message:
            raise ChatValidationError(
                message="Message cannot be None",
                field="message",
                value=None
            )
        
        if not message.message_id:
            raise ChatValidationError(
                message="Message ID cannot be empty",
                field="message_id",
                value=message.message_id
            )
        
        if not message.session_id:
            raise ChatValidationError(
                message="Session ID cannot be empty",
                field="session_id",
                value=message.session_id
            )
        
        if not message.content or not message.content.strip():
            raise ChatValidationError(
                message="Message content cannot be empty",
                field="content",
                value=message.content
            )

        try:
            # Ensure collection exists
            await self.ensure_chat_collection_exists()
            
            # Chunk the message content
            chunks = self._chunk_message_content(message.content)
            
            # Check for resource limits
            if len(chunks) > 50:  # Reasonable limit for chunks per message
                raise ChatResourceError(
                    message=f"Message too large: {len(chunks)} chunks (max 50)",
                    resource_type="message_chunks",
                    current_usage=f"{len(chunks)} chunks"
                )
            
            point_ids = []
            
            log.info(f"Uploading message {message.message_id} in {len(chunks)} chunks to {self.collection_name}")
            
            # Process each chunk
            points_to_upload = []
            for chunk_text, chunk_index, total_chunks in chunks:
                try:
                    # Generate vector for this chunk
                    vector = await self.generate_message_vector(chunk_text)
                    
                    # Create unique point ID for this chunk
                    point_id = str(uuid.uuid4())
                    point_ids.append(point_id)
                    
                    # Prepare payload with all necessary metadata
                    payload = {
                        "message_id": message.message_id,
                        "session_id": message.session_id,
                        "conversation_id": message.conversation_id,
                        "username": message.username,
                        "role": message.role.value,
                        "content": chunk_text,
                        "philosopher_collection": message.philosopher_collection,
                        "created_at": message.created_at.isoformat(),
                        "chunk_index": chunk_index,
                        "total_chunks": total_chunks,
                        "original_content_length": len(message.content)
                    }
                    
                    # Create point for batch upload
                    point = models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload
                    )
                    points_to_upload.append(point)
                    
                except Exception as e:
                    log.error(f"Failed to process chunk {chunk_index} for message {message.message_id}: {e}")
                    raise ChatVectorStoreError(
                        message=f"Failed to process message chunk {chunk_index}: {str(e)}",
                        operation="process_message_chunk",
                        collection_name=self.collection_name,
                        session_id=message.session_id,
                        details={
                            "message_id": message.message_id,
                            "chunk_index": chunk_index,
                            "error": str(e)
                        }
                    )
            
            # Batch upload all chunks
            try:
                await self.execute_with_retries(
                    lambda: self.qclient.upsert(
                        collection_name=self.collection_name,
                        points=points_to_upload
                    ),
                    operation_name=f"Upload message {message.message_id} to Qdrant"
                )
                
                log.info(f"Successfully uploaded message {message.message_id} with {len(point_ids)} chunks")
                return point_ids
                
            except Exception as e:
                log.error(f"Failed to upload points to Qdrant for message {message.message_id}: {e}")
                raise ChatVectorStoreError(
                    message=f"Failed to upload message points to Qdrant: {str(e)}",
                    operation="upsert_message_points",
                    collection_name=self.collection_name,
                    session_id=message.session_id,
                    details={
                        "message_id": message.message_id,
                        "points_count": len(points_to_upload),
                        "error": str(e)
                    }
                )
            
        except (ChatValidationError, ChatResourceError, ChatVectorStoreError):
            raise
        except Exception as e:
            log.error(f"Unexpected error uploading message to Qdrant: {e}")
            raise ChatVectorStoreError(
                message=f"Unexpected error during message upload: {str(e)}",
                operation="upload_message_to_qdrant",
                collection_name=self.collection_name,
                session_id=message.session_id if message else None,
                details={
                    "message_id": message.message_id if message else None,
                    "error_type": type(e).__name__,
                    "error": str(e)
                }
            )

    async def batch_upload_messages(self, messages: List[ChatMessage]) -> Dict[str, List[str]]:
        """
        Upload multiple messages to Qdrant in batches for efficiency.
        
        Args:
            messages: List of ChatMessage instances to upload
            
        Returns:
            Dictionary mapping message_id to list of point IDs
            
        Raises:
            LLMError: If batch upload fails
        """
        if not messages:
            return {}
        
        try:
            # Ensure collection exists
            await self.ensure_chat_collection_exists()
            
            result_mapping = {}
            batch_size = 10  # Process in smaller batches to avoid timeouts
            
            for i in range(0, len(messages), batch_size):
                batch = messages[i:i + batch_size]
                log.info(f"Processing batch {i//batch_size + 1}/{(len(messages) + batch_size - 1)//batch_size}")
                
                # Process each message in the batch
                for message in batch:
                    try:
                        point_ids = await self.upload_message_to_qdrant(message)
                        result_mapping[message.message_id] = point_ids
                    except Exception as e:
                        log.error(f"Failed to upload message {message.message_id}: {e}")
                        # Continue with other messages, don't fail the entire batch
                        result_mapping[message.message_id] = []
                
                # Small delay between batches to avoid overwhelming the service
                if i + batch_size < len(messages):
                    await asyncio.sleep(0.1)
            
            successful_uploads = sum(1 for point_ids in result_mapping.values() if point_ids)
            log.info(f"Batch upload completed: {successful_uploads}/{len(messages)} messages uploaded successfully")
            
            return result_mapping
            
        except Exception as e:
            log.error(f"Batch upload failed: {e}")
            raise LLMError(f"Batch message upload failed: {str(e)}")

    @monitor_chat_operation("search_messages")
    @vector_store_fallback_decorator(fallback_operation=lambda *args, **kwargs: [])
    async def search_messages(self, session_id: str, query: str, limit: int = 10,
                            philosopher_filter: Optional[str] = None,
                            username: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search chat messages using semantic vector search with optional fusion enhancement.

        When fusion is enabled (APP_USE_FUSION_SEARCH=true), uses ExpansionService to generate
        multiple enhanced queries and fuses results for improved relevance.

        Args:
            session_id: Session ID to filter results (ensures privacy isolation)
            query: Search query text
            limit: Maximum number of results to return
            philosopher_filter: Optional philosopher collection filter
            username: Optional username for user-specific filtering

        Returns:
            List of search results with message data and relevance scores

        Raises:
            ChatValidationError: If input validation fails
            ChatPrivacyError: If privacy validation fails
            ChatVectorStoreError: If search fails
        """
        # Input validation
        if not session_id or not session_id.strip():
            raise ChatValidationError(
                message="Session ID is required for chat message search",
                field="session_id",
                value=session_id
            )
        
        if not query or not query.strip():
            raise ChatValidationError(
                message="Search query cannot be empty",
                field="query",
                value=query
            )
        
        if limit <= 0 or limit > 100:
            raise ChatValidationError(
                message="Limit must be between 1 and 100",
                field="limit",
                value=limit
            )
        
        if len(query) > 10000:  # Reasonable limit for search queries
            raise ChatValidationError(
                message="Search query too long (max 10,000 characters)",
                field="query",
                value=f"Length: {len(query)}"
            )

        try:
            # Check if fusion search should be used
            if self.use_fusion and self.expansion_service:
                log.info(f"Using fusion search for session {session_id} with methods: {self.fusion_methods}")
                return await self._search_with_fusion(
                    session_id=session_id,
                    query=query,
                    limit=limit,
                    philosopher_filter=philosopher_filter,
                    username=username
                )
            else:
                # Fall back to standard vector search
                log.info(f"Using standard vector search for session {session_id}")
                return await self._search_standard(
                    session_id=session_id,
                    query=query,
                    limit=limit,
                    philosopher_filter=philosopher_filter,
                    username=username
                )
                
        except (ChatValidationError, ChatPrivacyError, ChatVectorStoreError):
            raise
        except Exception as e:
            log.error(f"Unexpected error during chat message search: {e}")
            raise ChatVectorStoreError(
                message=f"Unexpected error during message search: {str(e)}",
                operation="search_messages",
                collection_name=self.collection_name,
                session_id=session_id,
                details={
                    "query_length": len(query),
                    "limit": limit,
                    "error_type": type(e).__name__,
                    "fusion_enabled": self.use_fusion
                }
            )

    async def _search_with_fusion(self, session_id: str, query: str, limit: int,
                                philosopher_filter: Optional[str] = None,
                                username: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search using fusion with query expansion via ExpansionService.
        
        Uses the existing expand_query() API to generate enhanced queries and fuse results,
        while maintaining session filtering and privacy controls.
        """
        try:
            # Use ExpansionService to expand query and get fused results
            expansion_result = await self.expansion_service.expand_query(
                query=query,
                collection=self.collection_name,
                methods=self.fusion_methods,
                rrf_k=self.fusion_rrf_k,
                max_results=limit * 2,  # Get more results for better fusion
                enable_prf=False,
                # Pass session filtering to ensure privacy
                session_id=session_id,
                philosopher_filter=philosopher_filter
            )
            
            # Extract the fused results from expansion
            fused_results = expansion_result.retrieval_results[:limit]
            
            # Convert Qdrant points to chat message format with privacy validation
            formatted_results = []
            for result in fused_results:
                # Ensure result has proper structure (from Qdrant)
                if not hasattr(result, 'payload') or not hasattr(result, 'score'):
                    log.warning(f"Skipping invalid result structure in fusion search: {type(result)}")
                    continue
                
                # Double-check privacy: ensure result belongs to the session  
                result_session_id = result.payload.get("session_id")
                if result_session_id != session_id:
                    log.error(f"Privacy violation: fusion result from different session {result_session_id} for query session {session_id}")
                    raise ChatPrivacyError(
                        message="Fusion search result privacy violation detected",
                        violation_type="cross_session_result_fusion",
                        session_id=session_id,
                        details={
                            "result_session_id": result_session_id,
                            "point_id": getattr(result, 'id', 'unknown')
                        }
                    )
                
                # Apply philosopher filter if specified
                if philosopher_filter:
                    result_philosopher = result.payload.get("philosopher_collection")
                    if result_philosopher != philosopher_filter:
                        continue  # Skip results that don't match philosopher filter

                # Apply username filter if specified
                if username:
                    result_username = result.payload.get("username")
                    if result_username != username:
                        continue  # Skip results that don't match username filter

                message_data = {
                    "message_id": result.payload.get("message_id"),
                    "conversation_id": result.payload.get("conversation_id"),
                    "session_id": result.payload.get("session_id"),
                    "username": result.payload.get("username"),
                    "role": result.payload.get("role"),
                    "content": result.payload.get("content"),
                    "philosopher_collection": result.payload.get("philosopher_collection"),
                    "created_at": result.payload.get("created_at"),
                    "chunk_index": result.payload.get("chunk_index", 0),
                    "total_chunks": result.payload.get("total_chunks", 1),
                    "relevance_score": result.score,
                    "point_id": getattr(result, 'id', None),
                    "fusion_metadata": {
                        "methods_used": expansion_result.expanded_queries.keys(),
                        "total_queries_generated": len([q for queries in expansion_result.expanded_queries.values() for q in queries]),
                        "rrf_k": self.fusion_rrf_k
                    }
                }
                formatted_results.append(message_data)
            
            log.info(f"Fusion search found {len(formatted_results)} relevant messages for session {session_id}")
            return formatted_results
            
        except Exception as e:
            log.error(f"Fusion search failed for session {session_id}: {e} - falling back to standard search")
            # Graceful fallback to standard search on fusion failure
            return await self._search_standard(
                session_id=session_id,
                query=query,
                limit=limit,
                philosopher_filter=philosopher_filter,
                username=username
            )

    async def _search_standard(self, session_id: str, query: str, limit: int,
                             philosopher_filter: Optional[str] = None,
                             username: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Standard vector search implementation (original search_messages logic).

        This preserves the existing search behavior as a fallback and for when fusion is disabled.
        """
        # Generate query vector
        try:
            query_vector = await self.generate_message_vector(query)
        except Exception as e:
            log.error(f"Failed to generate query vector for search: {e}")
            raise ChatVectorStoreError(
                message=f"Failed to generate search vector: {str(e)}",
                operation="generate_query_vector",
                collection_name=self.collection_name,
                session_id=session_id,
                details={"query_length": len(query)}
            )

        # Build filter conditions - session_id is mandatory for privacy
        filter_conditions = [
            models.FieldCondition(
                key="session_id",
                match=models.MatchValue(value=session_id)
            )
        ]

        # Add optional username filter
        if username:
            if len(username) > 255:  # Reasonable limit
                raise ChatValidationError(
                    message="Username too long (max 255 characters)",
                    field="username",
                    value=f"Length: {len(username)}"
                )

            filter_conditions.append(
                models.FieldCondition(
                    key="username",
                    match=models.MatchValue(value=username)
                )
            )

        # Add optional philosopher filter with validation
        if philosopher_filter:
            if len(philosopher_filter) > 100:  # Reasonable limit
                raise ChatValidationError(
                    message="Philosopher filter too long (max 100 characters)",
                    field="philosopher_filter",
                    value=f"Length: {len(philosopher_filter)}"
                )

            filter_conditions.append(
                models.FieldCondition(
                    key="philosopher_collection",
                    match=models.MatchValue(value=philosopher_filter)
                )
            )
        
        search_filter = models.Filter(must=filter_conditions)
        
        log.info(f"Searching chat messages for session {session_id} with query: {query[:100]}...")
        
        # Execute search with session filtering
        try:
            search_results = await self.execute_with_retries(
                lambda: self.qclient.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=search_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False  # Don't return vectors to save bandwidth
                ),
                operation_name=f"Search chat messages for session {session_id}"
            )
        except Exception as e:
            log.error(f"Qdrant search failed for session {session_id}: {e}")
            raise ChatVectorStoreError(
                message=f"Vector search operation failed: {str(e)}",
                operation="qdrant_search",
                collection_name=self.collection_name,
                session_id=session_id,
                details={
                    "query_length": len(query),
                    "limit": limit,
                    "philosopher_filter": philosopher_filter,
                    "username": username
                }
            )

        # Convert results to message format with privacy validation
        formatted_results = []
        for result in search_results:
            # Double-check privacy: ensure result belongs to the session
            result_session_id = result.payload.get("session_id")
            if result_session_id != session_id:
                log.error(f"Privacy violation: search result from different session {result_session_id} for query session {session_id}")
                raise ChatPrivacyError(
                    message="Search result privacy violation detected",
                    violation_type="cross_session_result",
                    session_id=session_id,
                    details={
                        "result_session_id": result_session_id,
                        "point_id": result.id
                    }
                )

            message_data = {
                "message_id": result.payload.get("message_id"),
                "conversation_id": result.payload.get("conversation_id"),
                "session_id": result.payload.get("session_id"),
                "username": result.payload.get("username"),
                "role": result.payload.get("role"),
                "content": result.payload.get("content"),
                "philosopher_collection": result.payload.get("philosopher_collection"),
                "created_at": result.payload.get("created_at"),
                "chunk_index": result.payload.get("chunk_index", 0),
                "total_chunks": result.payload.get("total_chunks", 1),
                "relevance_score": result.score,
                "point_id": result.id
            }
            formatted_results.append(message_data)

        log.info(f"Found {len(formatted_results)} relevant messages for session {session_id}")
        return formatted_results

    async def search_conversation_context(self, session_id: str, query: str, 
                                        conversation_id: Optional[str] = None,
                                        limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search for relevant conversation context within a specific conversation or session.
        
        Args:
            session_id: Session ID for privacy filtering
            query: Search query text
            conversation_id: Optional specific conversation to search within
            limit: Maximum number of context messages to return
            
        Returns:
            List of relevant conversation messages for context
        """
        try:
            # Build filter conditions
            filter_conditions = [
                models.FieldCondition(
                    key="session_id",
                    match=models.MatchValue(value=session_id)
                )
            ]
            
            # Add conversation filter if specified
            if conversation_id:
                filter_conditions.append(
                    models.FieldCondition(
                        key="conversation_id",
                        match=models.MatchValue(value=conversation_id)
                    )
                )
            
            # Generate query vector
            query_vector = await self.generate_message_vector(query)
            search_filter = models.Filter(must=filter_conditions)
            
            # Search for relevant context
            search_results = await self.execute_with_retries(
                lambda: self.qclient.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=search_filter,
                    limit=limit * 2,  # Get more results to filter and deduplicate
                    with_payload=True,
                    with_vectors=False
                ),
                operation_name=f"Search conversation context for session {session_id}"
            )
            
            # Group by message_id and take the best chunk for each message
            message_groups = {}
            for result in search_results:
                message_id = result.payload.get("message_id")
                if message_id not in message_groups or result.score > message_groups[message_id]["score"]:
                    message_groups[message_id] = {
                        "message_id": message_id,
                        "conversation_id": result.payload.get("conversation_id"),
                        "role": result.payload.get("role"),
                        "content": result.payload.get("content"),
                        "philosopher_collection": result.payload.get("philosopher_collection"),
                        "created_at": result.payload.get("created_at"),
                        "score": result.score
                    }
            
            # Sort by relevance and return top results
            context_messages = list(message_groups.values())
            context_messages.sort(key=lambda x: x["score"], reverse=True)
            
            return context_messages[:limit]
            
        except Exception as e:
            log.error(f"Conversation context search failed: {e}")
            raise LLMError(f"Conversation context search failed: {str(e)}")

    def _reconstruct_message_from_chunks(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reconstruct a complete message from its chunks.
        
        Args:
            chunks: List of message chunks with chunk_index and content
            
        Returns:
            Reconstructed message with complete content
        """
        if not chunks:
            return {}
        
        # Sort chunks by chunk_index
        sorted_chunks = sorted(chunks, key=lambda x: x.get("chunk_index", 0))
        
        # Reconstruct content
        full_content = " ".join(chunk["content"] for chunk in sorted_chunks)
        
        # Use metadata from the first chunk (they should all be the same)
        base_message = sorted_chunks[0].copy()
        base_message["content"] = full_content
        base_message.pop("chunk_index", None)
        base_message.pop("total_chunks", None)
        
        return base_message

    async def get_message_chunks(self, message_id: str, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all chunks for a specific message with session validation.
        
        Args:
            message_id: ID of the message to retrieve
            session_id: Session ID for privacy validation
            
        Returns:
            List of message chunks
        """
        try:
            # Search for all chunks of this message with session filtering
            filter_conditions = [
                models.FieldCondition(
                    key="message_id",
                    match=models.MatchValue(value=message_id)
                ),
                models.FieldCondition(
                    key="session_id",
                    match=models.MatchValue(value=session_id)
                )
            ]
            
            search_filter = models.Filter(must=filter_conditions)
            
            # Use scroll to get all chunks (not limited by search limit)
            scroll_result = await self.execute_with_retries(
                lambda: self.qclient.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=search_filter,
                    with_payload=True,
                    with_vectors=False
                ),
                operation_name=f"Get chunks for message {message_id}"
            )
            
            chunks = []
            for point in scroll_result[0]:  # scroll returns (points, next_page_offset)
                chunk_data = {
                    "content": point.payload.get("content"),
                    "chunk_index": point.payload.get("chunk_index", 0),
                    "total_chunks": point.payload.get("total_chunks", 1),
                    "point_id": point.id
                }
                chunks.append(chunk_data)
            
            return chunks
            
        except Exception as e:
            log.error(f"Failed to get message chunks: {e}")
            raise LLMError(f"Failed to retrieve message chunks: {str(e)}")

    async def delete_user_messages(self, session_id: str) -> bool:
        """
        Delete all messages for a specific session from Qdrant.
        
        Args:
            session_id: Session ID to delete messages for
            
        Returns:
            True if deletion was successful
            
        Raises:
            LLMError: If deletion fails
        """
        if not session_id or not session_id.strip():
            raise LLMError("Session ID is required for message deletion")
        
        try:
            log.info(f"Deleting all messages for session {session_id} from {self.collection_name}")
            
            # Create filter for session messages
            delete_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="session_id",
                        match=models.MatchValue(value=session_id)
                    )
                ]
            )
            
            # Delete points matching the filter
            delete_result = await self.execute_with_retries(
                lambda: self.qclient.delete(
                    collection_name=self.collection_name,
                    points_selector=models.FilterSelector(filter=delete_filter)
                ),
                operation_name=f"Delete messages for session {session_id}"
            )
            
            log.info(f"Successfully deleted messages for session {session_id}")
            return True
            
        except Exception as e:
            log.error(f"Failed to delete user messages: {e}")
            raise LLMError(f"Message deletion failed: {str(e)}")

    async def get_collection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the chat collection.
        
        Returns:
            Dictionary with collection statistics
        """
        try:
            collection_info = await self.execute_with_retries(
                lambda: self.qclient.get_collection(self.collection_name),
                operation_name=f"Get stats for {self.collection_name}"
            )
            
            return {
                "collection_name": self.collection_name,
                "points_count": collection_info.points_count,
                "vectors_count": collection_info.vectors_count,
                "indexed_vectors_count": collection_info.indexed_vectors_count,
                "status": collection_info.status,
                "optimizer_status": collection_info.optimizer_status,
                "config": {
                    "vector_size": collection_info.config.params.vectors.size,
                    "distance": collection_info.config.params.vectors.distance
                }
            }
            
        except Exception as e:
            log.error(f"Failed to get collection stats: {e}")
            return {"error": str(e)}