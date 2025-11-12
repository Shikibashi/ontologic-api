"""
Batch processing utilities for chat history operations.

Provides efficient batch operations for vector generation, upload,
and data processing with progress tracking and error handling.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Callable, AsyncGenerator
from dataclasses import dataclass
from sqlmodel import select, and_
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_models import ChatMessage, ChatConversation
from app.core.database import AsyncSessionLocal
from app.core.logger import log
from app.services.chat_qdrant_service import ChatQdrantService


DEFAULT_MAX_RESULTS_GUARD = 50_000


@dataclass
class BatchProcessingResult:
    """Result of a batch processing operation."""
    total_processed: int
    successful: int
    failed: int
    errors: List[str]
    duration_seconds: float
    batch_id: str


@dataclass
class BatchProcessingProgress:
    """Progress information for batch operations."""
    batch_id: str
    total_items: int
    processed_items: int
    current_batch: int
    total_batches: int
    start_time: datetime
    estimated_completion: Optional[datetime] = None
    current_operation: str = ""


class ChatBatchProcessor:
    """
    Batch processor for chat history operations with progress tracking.
    
    Handles large-scale operations like vector generation, Qdrant uploads,
    and data migrations with proper error handling and recovery.
    """
    
    def __init__(
        self,
        batch_size: int = 100,
        max_concurrent: int = 5,
        progress_callback: Optional[Callable[[BatchProcessingProgress], None]] = None,
        max_results_guard: Optional[int] = DEFAULT_MAX_RESULTS_GUARD
    ):
        """
        Initialize batch processor.
        
        Args:
            batch_size: Number of items to process per batch
            max_concurrent: Maximum concurrent operations
            progress_callback: Optional callback for progress updates
            max_results_guard: Maximum number of records to process per run (None disables guard)
        """
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.progress_callback = progress_callback
        self._active_batches: Dict[str, BatchProcessingProgress] = {}
        self.max_results_guard = max_results_guard
    
    async def batch_generate_vectors(
        self,
        session_id: Optional[str] = None,
        missing_vectors_only: bool = True,
        qdrant_service: Optional[ChatQdrantService] = None
    ) -> BatchProcessingResult:
        """
        Generate vectors for chat messages in batches.

        Args:
            session_id: Optional session to filter by
            missing_vectors_only: Only process messages without Qdrant point IDs
            qdrant_service: ChatQdrantService instance for vector operations
            
        Returns:
            BatchProcessingResult with operation statistics
        """
        batch_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)

        try:
            qdrant_service = self._require_qdrant_service(qdrant_service)

            async with AsyncSessionLocal() as db_session:
                total_messages = await self._count_messages_for_vector_processing(
                    db_session,
                    session_id,
                    missing_vectors_only,
                )

                if not total_messages:
                    log.info("No messages found for vector processing")
                    return BatchProcessingResult(
                        total_processed=0,
                        successful=0,
                        failed=0,
                        errors=[],
                        duration_seconds=0.0,
                        batch_id=batch_id,
                    )

                target_total = self._apply_max_guard(total_messages, "Vector generation")

                if target_total == 0:
                    log.info("Vector generation skipped due to max results guard")
                    return BatchProcessingResult(
                        total_processed=0,
                        successful=0,
                        failed=0,
                        errors=[],
                        duration_seconds=0.0,
                        batch_id=batch_id,
                    )

                progress = BatchProcessingProgress(
                    batch_id=batch_id,
                    total_items=target_total,
                    processed_items=0,
                    current_batch=0,
                    total_batches=max(1, (target_total + self.batch_size - 1) // self.batch_size),
                    start_time=start_time,
                    current_operation="Generating vectors",
                )
                self._active_batches[batch_id] = progress

                successful = 0
                failed = 0
                errors: List[str] = []
                processed_items = 0
                batch_index = 0

                async for batch in self._get_messages_for_vector_processing(
                    db_session,
                    session_id,
                    missing_vectors_only,
                    chunk_size=self.batch_size,
                    max_results=target_total,
                ):
                    if not batch:
                        continue

                    batch_index += 1
                    progress.current_batch = batch_index

                    semaphore = asyncio.Semaphore(self.max_concurrent)
                    tasks = [
                        self._process_message_vector(message, qdrant_service, semaphore)
                        for message in batch
                    ]

                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                    for message_obj, result in zip(batch, batch_results):
                        if isinstance(result, Exception):
                            failed += 1
                            errors.append(f"Message {message_obj.message_id}: {str(result)}")
                        elif result:
                            successful += 1
                        else:
                            failed += 1
                            errors.append(f"Message {message_obj.message_id}: Unknown error")

                    processed_items += len(batch)
                    progress.processed_items = min(processed_items, target_total)

                    if self.progress_callback:
                        self.progress_callback(progress)

                    log.info(
                        "Processed batch %d/%d for vector generation",
                        progress.current_batch,
                        progress.total_batches,
                    )

                    if processed_items >= target_total:
                        break

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            result = BatchProcessingResult(
                total_processed=processed_items,
                successful=successful,
                failed=failed,
                errors=errors,
                duration_seconds=duration,
                batch_id=batch_id,
            )

            log.info(
                "Batch vector generation completed: %d/%d successful",
                successful,
                processed_items,
            )
            return result

        except Exception as e:
            log.error(f"Batch vector generation failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return BatchProcessingResult(
                total_processed=0,
                successful=0,
                failed=1,
                errors=[str(e)],
                duration_seconds=duration,
                batch_id=batch_id
            )
        finally:
            # Clean up progress tracking
            self._active_batches.pop(batch_id, None)
    
    async def batch_upload_to_qdrant(
        self,
        session_id: Optional[str] = None,
        qdrant_service: Optional[ChatQdrantService] = None
    ) -> BatchProcessingResult:
        """
        Upload chat messages to Qdrant in batches.
        
        Args:
            session_id: Optional session to filter by
            qdrant_service: ChatQdrantService instance for uploads
            
        Returns:
            BatchProcessingResult with operation statistics
        """
        batch_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)
        
        try:
            qdrant_service = self._require_qdrant_service(qdrant_service)

            async with AsyncSessionLocal() as db_session:
                total_messages = await self._count_messages_for_qdrant_upload(
                    db_session,
                    session_id,
                )

                if not total_messages:
                    log.info("No messages found for Qdrant upload")
                    return BatchProcessingResult(
                        total_processed=0,
                        successful=0,
                        failed=0,
                        errors=[],
                        duration_seconds=0.0,
                        batch_id=batch_id,
                    )

                target_total = self._apply_max_guard(total_messages, "Qdrant upload")

                if target_total == 0:
                    log.info("Qdrant upload skipped due to max results guard")
                    return BatchProcessingResult(
                        total_processed=0,
                        successful=0,
                        failed=0,
                        errors=[],
                        duration_seconds=0.0,
                        batch_id=batch_id,
                    )

                progress = BatchProcessingProgress(
                    batch_id=batch_id,
                    total_items=target_total,
                    processed_items=0,
                    current_batch=0,
                    total_batches=max(1, (target_total + self.batch_size - 1) // self.batch_size),
                    start_time=start_time,
                    current_operation="Uploading to Qdrant",
                )
                self._active_batches[batch_id] = progress

                successful = 0
                failed = 0
                errors: List[str] = []
                processed_items = 0
                batch_index = 0

                async for batch in self._get_messages_for_qdrant_upload(
                    db_session,
                    session_id,
                    chunk_size=self.batch_size,
                    max_results=target_total,
                ):
                    if not batch:
                        continue

                    batch_index += 1
                    progress.current_batch = batch_index

                    semaphore = asyncio.Semaphore(self.max_concurrent)
                    tasks = [
                        self._upload_message_to_qdrant(message, qdrant_service, semaphore)
                        for message in batch
                    ]

                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                    for message_obj, result in zip(batch, batch_results):
                        if isinstance(result, Exception):
                            failed += 1
                            errors.append(f"Message {message_obj.message_id}: {str(result)}")
                        elif result:
                            successful += 1
                        else:
                            failed += 1
                            errors.append(f"Message {message_obj.message_id}: Upload failed")

                    processed_items += len(batch)
                    progress.processed_items = min(processed_items, target_total)

                    if self.progress_callback:
                        self.progress_callback(progress)

                    log.info(
                        "Processed batch %d/%d for Qdrant upload",
                        progress.current_batch,
                        progress.total_batches,
                    )

                    if processed_items >= target_total:
                        break

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            result = BatchProcessingResult(
                total_processed=processed_items,
                successful=successful,
                failed=failed,
                errors=errors,
                duration_seconds=duration,
                batch_id=batch_id,
            )

            log.info(
                "Batch Qdrant upload completed: %d/%d successful",
                successful,
                processed_items,
            )
            return result

        except Exception as e:
            log.error(f"Batch Qdrant upload failed: {e}")
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            return BatchProcessingResult(
                total_processed=0,
                successful=0,
                failed=1,
                errors=[str(e)],
                duration_seconds=duration,
                batch_id=batch_id
            )
        finally:
            # Clean up progress tracking
            self._active_batches.pop(batch_id, None)
    
    async def get_batch_progress(self, batch_id: str) -> Optional[BatchProcessingProgress]:
        """Get progress information for an active batch operation."""
        return self._active_batches.get(batch_id)
    
    def get_active_batches(self) -> List[BatchProcessingProgress]:
        """Get all currently active batch operations."""
        return list(self._active_batches.values())

    @staticmethod
    def _require_qdrant_service(qdrant_service: Optional[ChatQdrantService]) -> ChatQdrantService:
        """Ensure a Qdrant service instance is available."""
        if qdrant_service is None:
            raise ValueError("ChatQdrantService instance is required for Qdrant operations")
        return qdrant_service

    @staticmethod
    def _build_message_filters(
        session_id: Optional[str],
        require_missing_qdrant_point: bool
    ) -> List[Any]:
        """Build common filters for chat message selection."""
        filters: List[Any] = []
        if session_id:
            filters.append(ChatMessage.session_id == session_id)
        if require_missing_qdrant_point:
            filters.append(ChatMessage.qdrant_point_id.is_(None))
        return filters

    def _apply_max_guard(self, total: int, operation: str) -> int:
        """Apply the max results guard and warn when truncating work."""
        if self.max_results_guard is not None and total > self.max_results_guard:
            log.warning(
                "%s limited to %d records by max_results_guard (requested %d)",
                operation,
                self.max_results_guard,
                total,
            )
            return self.max_results_guard
        return total

    async def _stream_chat_messages(
        self,
        db_session: AsyncSession,
        statement,
        chunk_size: int,
        max_results: Optional[int] = None
    ) -> AsyncGenerator[List[ChatMessage], None]:
        """Stream chat messages in bounded chunks to avoid large memory usage."""
        statement = statement.execution_options(stream_results=True)
        stream = await db_session.stream_scalars(statement)
        processed = 0
        chunk: List[ChatMessage] = []

        try:
            async for message in stream:
                if max_results is not None and processed >= max_results:
                    break

                chunk.append(message)
                processed += 1

                if len(chunk) >= chunk_size:
                    yield chunk
                    chunk = []

            if chunk and (max_results is None or processed <= max_results):
                yield chunk
        finally:
            await stream.close()

    async def _count_messages_for_vector_processing(
        self,
        db_session: AsyncSession,
        session_id: Optional[str],
        missing_vectors_only: bool
    ) -> int:
        """Count messages eligible for vector processing."""
        filters = self._build_message_filters(session_id, missing_vectors_only)
        count_stmt = select(func.count(ChatMessage.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        result = await db_session.execute(count_stmt)
        return int(result.scalar_one() or 0)

    async def _count_messages_for_qdrant_upload(
        self,
        db_session: AsyncSession,
        session_id: Optional[str]
    ) -> int:
        """Count messages missing a Qdrant point ID."""
        filters = self._build_message_filters(session_id, True)
        count_stmt = select(func.count(ChatMessage.id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        result = await db_session.execute(count_stmt)
        return int(result.scalar_one() or 0)

    async def _get_messages_for_vector_processing(
        self,
        db_session: AsyncSession,
        session_id: Optional[str],
        missing_vectors_only: bool,
        chunk_size: Optional[int] = None,
        max_results: Optional[int] = None
    ) -> AsyncGenerator[List[ChatMessage], None]:
        """Stream messages that need vector processing in bounded chunks."""
        statement = select(ChatMessage)
        filters = self._build_message_filters(session_id, missing_vectors_only)

        if filters:
            statement = statement.where(*filters)

        # Order by creation time for consistent processing
        statement = statement.order_by(ChatMessage.created_at.asc())

        effective_chunk_size = chunk_size or self.batch_size
        async for chunk in self._stream_chat_messages(
            db_session,
            statement,
            effective_chunk_size,
            max_results=max_results,
        ):
            yield chunk
    
    async def _get_messages_for_qdrant_upload(
        self,
        db_session: AsyncSession,
        session_id: Optional[str],
        chunk_size: Optional[int] = None,
        max_results: Optional[int] = None
    ) -> AsyncGenerator[List[ChatMessage], None]:
        """Stream messages that need Qdrant upload (no point ID yet)."""
        statement = select(ChatMessage)
        filters = self._build_message_filters(session_id, True)

        if filters:
            statement = statement.where(*filters)

        statement = statement.order_by(ChatMessage.created_at.asc())

        effective_chunk_size = chunk_size or self.batch_size
        async for chunk in self._stream_chat_messages(
            db_session,
            statement,
            effective_chunk_size,
            max_results=max_results,
        ):
            yield chunk
    
    async def _process_message_vector(
        self,
        message: ChatMessage,
        qdrant_service: Optional[ChatQdrantService],
        semaphore: asyncio.Semaphore
    ) -> bool:
        """Process vector generation for a single message."""
        service = self._require_qdrant_service(qdrant_service)

        try:
            async with semaphore:
                point_id = await service.upload_message_to_qdrant(message)
        except Exception as e:
            log.error(f"Error processing vector for message {message.message_id}: {e}")
            return False

        if not point_id:
            return False

        try:
            async with AsyncSessionLocal() as db_session:
                db_message = await db_session.get(ChatMessage, message.id)
                if db_message:
                    db_message.qdrant_point_id = point_id
                    db_session.add(db_message)
                    await db_session.commit()
            return True
        except Exception as db_error:
            log.error(
                f"Failed to persist Qdrant point for message {message.message_id}: {db_error}"
            )
            return False
    
    async def _upload_message_to_qdrant(
        self,
        message: ChatMessage,
        qdrant_service: Optional[ChatQdrantService],
        semaphore: asyncio.Semaphore
    ) -> bool:
        """Upload a single message to Qdrant."""
        service = self._require_qdrant_service(qdrant_service)

        try:
            async with semaphore:
                point_id = await service.upload_message_to_qdrant(message)
        except Exception as e:
            log.error(f"Error uploading message {message.message_id} to Qdrant: {e}")
            return False

        if not point_id:
            return False

        try:
            async with AsyncSessionLocal() as db_session:
                db_message = await db_session.get(ChatMessage, message.id)
                if db_message:
                    db_message.qdrant_point_id = point_id
                    db_session.add(db_message)
                    await db_session.commit()
            return True
        except Exception as db_error:
            log.error(
                f"Failed to persist Qdrant point for message {message.message_id}: {db_error}"
            )
            return False


async def batch_process_chat_vectors(
    session_id: Optional[str] = None,
    batch_size: int = 100,
    max_concurrent: int = 5,
    qdrant_service: Optional[ChatQdrantService] = None,
    progress_callback: Optional[Callable[[BatchProcessingProgress], None]] = None
) -> BatchProcessingResult:
    """
    Convenience function for batch vector processing.
    
    Args:
        session_id: Optional session to filter by
        batch_size: Number of items per batch
        max_concurrent: Maximum concurrent operations
        qdrant_service: ChatQdrantService instance required for vector processing
        progress_callback: Optional progress callback
        
    Returns:
        BatchProcessingResult with operation statistics
    """
    if qdrant_service is None:
        raise ValueError("ChatQdrantService instance must be provided for vector processing")

    processor = ChatBatchProcessor(
        batch_size=batch_size,
        max_concurrent=max_concurrent,
        progress_callback=progress_callback
    )
    return await processor.batch_generate_vectors(
        session_id=session_id,
        missing_vectors_only=True,
        qdrant_service=qdrant_service
    )


async def batch_upload_to_qdrant(
    session_id: Optional[str] = None,
    batch_size: int = 100,
    max_concurrent: int = 5,
    qdrant_service: Optional[ChatQdrantService] = None,
    progress_callback: Optional[Callable[[BatchProcessingProgress], None]] = None
) -> BatchProcessingResult:
    """
    Convenience function for batch Qdrant upload.
    
    Args:
        session_id: Optional session to filter by
        batch_size: Number of items per batch
        max_concurrent: Maximum concurrent operations
        qdrant_service: ChatQdrantService instance required for uploads
        progress_callback: Optional progress callback
        
    Returns:
        BatchProcessingResult with operation statistics
    """
    if qdrant_service is None:
        raise ValueError("ChatQdrantService instance must be provided for Qdrant upload")

    processor = ChatBatchProcessor(
        batch_size=batch_size,
        max_concurrent=max_concurrent,
        progress_callback=progress_callback
    )
    return await processor.batch_upload_to_qdrant(
        session_id=session_id,
        qdrant_service=qdrant_service
    )
