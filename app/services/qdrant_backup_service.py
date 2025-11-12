"""
Qdrant Backup Service for production to local sync operations.

This service provides functionality to backup Qdrant collections from production
to local development environments, enabling developers to work with realistic data
without affecting production systems.
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException

from app.core.logger import log
from app.core.exceptions import LLMTimeoutError, LLMUnavailableError


class BackupStatus(Enum):
    """Backup operation status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackupProgress:
    """Progress tracking for backup operations."""
    backup_id: str
    status: BackupStatus = BackupStatus.PENDING
    total_collections: int = 0
    completed_collections: int = 0
    current_collection: Optional[str] = None
    total_points: int = 0
    processed_points: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)
    
    @property
    def collection_progress_percent(self) -> float:
        """Calculate collection-level progress percentage."""
        if self.total_collections == 0:
            return 0.0
        return (self.completed_collections / self.total_collections) * 100
    
    @property
    def point_progress_percent(self) -> float:
        """Calculate point-level progress percentage."""
        if self.total_points == 0:
            return 0.0
        return (self.processed_points / self.total_points) * 100
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate operation duration in seconds."""
        if not self.start_time:
            return None
        end_time = self.end_time or datetime.now(timezone.utc)
        return (end_time - self.start_time).total_seconds()


@dataclass
class CollectionInfo:
    """Information about a Qdrant collection."""
    name: str
    vectors_count: int
    indexed_vectors_count: int
    points_count: int
    segments_count: int
    config: Dict[str, Any]
    payload_schema: Dict[str, Any] = field(default_factory=dict)


class QdrantBackupService:
    """
    Service for backing up Qdrant collections from production to local instances.
    
    Provides functionality for:
    - Dual Qdrant client management (production and local)
    - Collection backup with progress tracking
    - Error handling and retry logic
    - Data integrity validation
    """
    
    def __init__(self, production_config: Dict[str, Any], local_config: Dict[str, Any]):
        """
        Initialize backup service with production and local Qdrant configurations.
        
        Args:
            production_config: Configuration for production Qdrant instance
            local_config: Configuration for local Qdrant instance
        """
        self.production_config = production_config
        self.local_config = local_config
        
        # Initialize clients
        self.production_client = self._create_client(production_config, "production")
        self.local_client = self._create_client(local_config, "local")
        
        # Progress tracking
        self._active_backups: Dict[str, BackupProgress] = {}
        
        # Configuration
        self.timeout_seconds = production_config.get("timeout", 30)
        self.retry_attempts = max(1, int(production_config.get("retry_attempts", 3)))
        self.batch_size = production_config.get("backup_batch_size", 1000)
        
        log.info("QdrantBackupService initialized with production and local clients")
    
    def _create_client(self, config: Dict[str, Any], client_type: str) -> AsyncQdrantClient:
        """Create and configure a Qdrant client."""
        url = config.get("url")
        if not url:
            raise ValueError(f"URL is required for {client_type} Qdrant configuration")
        
        # Get API key from environment if specified
        api_key = None
        api_key_env = config.get("api_key_env")
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key and client_type == "production":
                raise ValueError(f"Environment variable {api_key_env} is required for production Qdrant authentication")
        
        timeout_seconds = config.get("timeout", 30)
        
        client = AsyncQdrantClient(
            url=url,
            port=config.get("port"),
            api_key=api_key,
            timeout=timeout_seconds
        )
        
        log.info(f"Created {client_type} Qdrant client for {url}")
        return client
    
    async def with_timeout(self, coro, timeout_seconds=None, operation_name="Backup operation"):
        """Wrapper for operations with timeout and proper error handling."""
        timeout_seconds = timeout_seconds or self.timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            log.error(f"{operation_name} timed out after {timeout_seconds}s")
            raise LLMTimeoutError(f"{operation_name} timed out after {timeout_seconds} seconds")
        except Exception as e:
            log.error(f"{operation_name} failed: {e}")
            raise LLMUnavailableError(f"{operation_name} failed: {str(e)}")
    
    async def execute_with_retries(self, operation, timeout_seconds=None, operation_name="Backup operation"):
        """Execute an async operation with retry and timeout handling."""
        attempts = self.retry_attempts
        last_error = None
        
        for attempt in range(1, attempts + 1):
            try:
                return await self.with_timeout(
                    operation(),
                    timeout_seconds=timeout_seconds,
                    operation_name=operation_name
                )
            except (LLMTimeoutError, LLMUnavailableError) as exc:
                last_error = exc
                if attempt >= attempts:
                    log.error(f"{operation_name} failed after {attempts} attempts")
                    raise
                backoff = min(2 ** (attempt - 1), 8)
                log.warning(
                    f"{operation_name} attempt {attempt} failed ({exc}). Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)
        
        if last_error:
            raise last_error
    
    async def validate_connections(self) -> Tuple[bool, bool]:
        """
        Validate both production and local Qdrant connections.
        
        Returns:
            Tuple of (production_valid, local_valid)
        """
        production_valid = False
        local_valid = False
        
        try:
            await self.execute_with_retries(
                lambda: self.production_client.get_collections(),
                timeout_seconds=10,
                operation_name="Production Qdrant connection validation"
            )
            production_valid = True
            log.info("Production Qdrant connection validated successfully")
        except Exception as e:
            log.error(f"Production Qdrant connection validation failed: {e}")
        
        try:
            await self.execute_with_retries(
                lambda: self.local_client.get_collections(),
                timeout_seconds=10,
                operation_name="Local Qdrant connection validation"
            )
            local_valid = True
            log.info("Local Qdrant connection validated successfully")
        except Exception as e:
            log.error(f"Local Qdrant connection validation failed: {e}")
        
        return production_valid, local_valid
    
    async def get_collection_info(self, collection_name: str, client: AsyncQdrantClient) -> CollectionInfo:
        """
        Retrieve detailed information about a collection.
        
        Args:
            collection_name: Name of the collection
            client: Qdrant client to use
            
        Returns:
            CollectionInfo object with collection details
        """
        try:
            # Get collection info
            collection_info = await self.execute_with_retries(
                lambda: client.get_collection(collection_name),
                operation_name=f"Get collection info for {collection_name}"
            )
            
            # Get collection statistics
            collection_stats = await self.execute_with_retries(
                lambda: client.count(collection_name),
                operation_name=f"Get collection stats for {collection_name}"
            )
            
            return CollectionInfo(
                name=collection_name,
                vectors_count=collection_info.vectors_count or 0,
                indexed_vectors_count=collection_info.indexed_vectors_count or 0,
                points_count=collection_stats.count,
                segments_count=collection_info.segments_count or 0,
                config=collection_info.config.dict() if collection_info.config else {},
                payload_schema=collection_info.payload_schema or {}
            )
            
        except Exception as e:
            log.error(f"Failed to get collection info for {collection_name}: {e}")
            raise
    
    async def list_collections(self, client: AsyncQdrantClient) -> List[str]:
        """
        List all collections in a Qdrant instance.
        
        Args:
            client: Qdrant client to use
            
        Returns:
            List of collection names
        """
        try:
            collections_response = await self.execute_with_retries(
                lambda: client.get_collections(),
                operation_name="List collections"
            )
            
            collection_names = [col.name for col in collections_response.collections]
            log.info(f"Found {len(collection_names)} collections")
            return collection_names
            
        except Exception as e:
            log.error(f"Failed to list collections: {e}")
            raise
    
    async def collection_exists(self, collection_name: str, client: AsyncQdrantClient) -> bool:
        """
        Check if a collection exists in the Qdrant instance.
        
        Args:
            collection_name: Name of the collection to check
            client: Qdrant client to use
            
        Returns:
            True if collection exists, False otherwise
        """
        try:
            collections = await self.list_collections(client)
            return collection_name in collections
        except Exception as e:
            log.error(f"Failed to check if collection {collection_name} exists: {e}")
            return False
    
    async def close(self):
        """Close both Qdrant client connections."""
        try:
            if hasattr(self, "production_client") and self.production_client is not None:
                await self.production_client.close()
                log.info("Production Qdrant client connection closed")
        except Exception as exc:
            log.warning(f"Failed to close production Qdrant client cleanly: {exc}")
        
        try:
            if hasattr(self, "local_client") and self.local_client is not None:
                await self.local_client.close()
                log.info("Local Qdrant client connection closed")
        except Exception as exc:
            log.warning(f"Failed to close local Qdrant client cleanly: {exc}")    

    def create_backup_progress(self, collections: List[str]) -> BackupProgress:
        """
        Create a new backup progress tracker.
        
        Args:
            collections: List of collections to backup
            
        Returns:
            BackupProgress object with unique backup ID
        """
        backup_id = str(uuid.uuid4())
        progress = BackupProgress(
            backup_id=backup_id,
            total_collections=len(collections),
            start_time=datetime.now(timezone.utc)
        )
        
        self._active_backups[backup_id] = progress
        log.info(f"Created backup progress tracker {backup_id} for {len(collections)} collections")
        return progress
    
    def get_backup_progress(self, backup_id: str) -> Optional[BackupProgress]:
        """
        Get backup progress by ID.
        
        Args:
            backup_id: Backup operation ID
            
        Returns:
            BackupProgress object or None if not found
        """
        return self._active_backups.get(backup_id)
    
    def update_backup_progress(self, backup_id: str, **kwargs):
        """
        Update backup progress with new values.
        
        Args:
            backup_id: Backup operation ID
            **kwargs: Fields to update
        """
        if backup_id in self._active_backups:
            progress = self._active_backups[backup_id]
            for key, value in kwargs.items():
                if hasattr(progress, key):
                    setattr(progress, key, value)
    
    async def backup_collection(
        self, 
        collection_name: str, 
        target_name: Optional[str] = None,
        overwrite: bool = False,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Backup a single collection from production to local.
        
        Args:
            collection_name: Name of the source collection
            target_name: Name for the target collection (defaults to source name)
            overwrite: Whether to overwrite existing target collection
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dictionary with backup results and statistics
        """
        target_name = target_name or collection_name
        
        log.info(f"Starting backup of collection '{collection_name}' to '{target_name}'")

        try:
            # Use extracted validation logic
            await self._validate_and_prepare_backup(collection_name, target_name, overwrite)

            # Get source collection info
            source_info = await self.get_collection_info(collection_name, self.production_client)
            log.info(f"Source collection has {source_info.points_count} points")
            
            # Create target collection with same configuration
            log.info(f"Creating target collection '{target_name}'")
            await self._create_collection_from_config(target_name, source_info.config)
            
            # Backup points in batches
            total_points = source_info.points_count
            processed_points = 0
            
            if total_points > 0:
                # Scroll through all points
                next_offset = None
                batch_count = 0

                while True:
                    # Get next batch of points (returns tuple: records, next_page_offset)
                    records, next_offset = await self.execute_with_retries(
                        lambda: self.production_client.scroll(
                            collection_name=collection_name,
                            limit=self.batch_size,
                            offset=next_offset,
                            with_payload=True,
                            with_vectors=True
                        ),
                        operation_name=f"Scroll collection {collection_name} batch {batch_count + 1}"
                    )

                    if not records:
                        break

                    batch_count += 1
                    batch_size = len(records)

                    log.info(f"Processing batch {batch_count}: {batch_size} points")

                    # Convert records to PointStruct objects using helper
                    points = self._records_to_points(records)

                    # Upload batch to target collection
                    await self.execute_with_retries(
                        lambda: self.local_client.upsert(
                            collection_name=target_name,
                            points=points
                        ),
                        operation_name=f"Upsert batch {batch_count} to {target_name}"
                    )

                    processed_points += batch_size

                    # Call progress callback if provided
                    if progress_callback:
                        progress_callback(processed_points, total_points)

                    log.info(f"Processed {processed_points}/{total_points} points ({(processed_points/total_points)*100:.1f}%)")

                    # Check if we've processed all points
                    if not next_offset:
                        break
            
            # Verify backup
            target_info = await self.get_collection_info(target_name, self.local_client)
            
            backup_result = {
                "source_collection": collection_name,
                "target_collection": target_name,
                "source_points": source_info.points_count,
                "target_points": target_info.points_count,
                "success": True,
                "processed_points": processed_points,
                "batches_processed": batch_count if total_points > 0 else 0
            }
            
            log.info(f"Backup completed successfully: {source_info.points_count} -> {target_info.points_count} points")
            return backup_result
            
        except Exception as e:
            log.error(f"Backup failed for collection '{collection_name}': {e}")
            return {
                "source_collection": collection_name,
                "target_collection": target_name,
                "success": False,
                "error": str(e),
                "processed_points": processed_points if 'processed_points' in locals() else 0
            }
    
    async def _create_collection_from_config(self, collection_name: str, source_config: Dict[str, Any]):
        """
        Create a collection using configuration from source collection.
        Handles both dense and sparse vectors.

        Args:
            collection_name: Name of the collection to create
            source_config: Configuration dictionary from source collection
        """
        try:
            params = source_config.get("params", {})

            # Extract dense vector configurations
            vectors_config = params.get("vectors", {})

            # Handle different vector configuration formats
            if isinstance(vectors_config, dict):
                # Multiple named vectors
                vectors = {}
                for vector_name, vector_config in vectors_config.items():
                    vectors[vector_name] = models.VectorParams(
                        size=vector_config.get("size", 4096),  # Default to Salesforce/sfr-embedding-mistral size
                        distance=models.Distance(vector_config.get("distance", "Cosine"))
                    )
            else:
                # Single vector configuration
                vectors = models.VectorParams(
                    size=vectors_config.get("size", 4096),  # Default to Salesforce/sfr-embedding-mistral size
                    distance=models.Distance(vectors_config.get("distance", "Cosine"))
                )

            # Extract sparse vector configurations (CRITICAL: handles sparse vectors)
            sparse_vectors_config = params.get("sparse_vectors")
            sparse_vectors = None
            if sparse_vectors_config:
                sparse_vectors = {}
                for sparse_name, sparse_config in sparse_vectors_config.items():
                    sparse_vectors[sparse_name] = models.SparseVectorParams(
                        index=sparse_config.get("index", {})
                    )
                log.info(f"Configured {len(sparse_vectors)} sparse vector(s) for collection '{collection_name}'")

            # Create collection with both dense and sparse vectors
            await self.execute_with_retries(
                lambda: self.local_client.create_collection(
                    collection_name=collection_name,
                    vectors_config=vectors,
                    sparse_vectors_config=sparse_vectors,
                    shard_number=params.get("shard_number", 1),
                    replication_factor=params.get("replication_factor", 1),
                    write_consistency_factor=params.get("write_consistency_factor"),
                    on_disk_payload=params.get("on_disk_payload")
                ),
                operation_name=f"Create collection {collection_name}"
            )

            log.info(f"Created collection '{collection_name}' with configuration from source (dense + sparse vectors)")

        except Exception as e:
            log.error(f"Failed to create collection '{collection_name}': {e}")
            raise

    async def _validate_and_prepare_backup(
        self,
        collection_name: str,
        target_name: str,
        overwrite: bool
    ) -> None:
        """
        Common validation and preparation logic for backup operations.

        Args:
            collection_name: Source collection name
            target_name: Target collection name
            overwrite: Whether to overwrite existing target

        Raises:
            ValueError: If validation fails
        """
        # Check if source collection exists
        if not await self.collection_exists(collection_name, self.production_client):
            raise ValueError(f"Source collection '{collection_name}' does not exist in production")

        # Check if target collection exists
        target_exists = await self.collection_exists(target_name, self.local_client)
        if target_exists and not overwrite:
            raise ValueError(
                f"Target collection '{target_name}' already exists. Use overwrite=True to replace it"
            )

        # Delete target collection if it exists and overwrite is True
        if target_exists and overwrite:
            log.info(f"Deleting existing target collection '{target_name}'")
            await self.execute_with_retries(
                lambda: self.local_client.delete_collection(target_name),
                operation_name=f"Delete existing collection {target_name}"
            )

    def _records_to_points(self, records: List[Any]) -> List[models.PointStruct]:
        """
        Convert scroll records to PointStruct objects for upsertion.

        Args:
            records: List of records from scroll operation

        Returns:
            List of PointStruct objects ready for upsert
        """
        return [
            models.PointStruct(
                id=record.id,
                vector=record.vector,
                payload=record.payload
            )
            for record in records
        ]

    async def backup_collections(
        self,
        collections: Optional[List[str]] = None,
        collection_filter: Optional[str] = None,
        target_prefix: Optional[str] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        Backup multiple collections with selective filtering.
        
        Args:
            collections: Specific collections to backup (if None, backup all)
            collection_filter: Filter pattern for collection names (supports wildcards)
            target_prefix: Prefix to add to target collection names
            overwrite: Whether to overwrite existing target collections
            
        Returns:
            Dictionary with backup results and statistics
        """
        # Create backup progress tracker
        backup_progress = self.create_backup_progress(collections or [])
        backup_id = backup_progress.backup_id
        
        try:
            backup_progress.status = BackupStatus.IN_PROGRESS
            
            # Get list of collections to backup
            if collections is None:
                # Get all collections from production
                all_collections = await self.list_collections(self.production_client)
                collections_to_backup = self._filter_collections(all_collections, collection_filter)
            else:
                collections_to_backup = collections
            
            # Update progress with actual collection count
            backup_progress.total_collections = len(collections_to_backup)
            
            log.info(f"Starting backup of {len(collections_to_backup)} collections")
            
            # Calculate total points for progress tracking
            total_points = 0
            collection_point_counts = {}
            
            for collection_name in collections_to_backup:
                try:
                    info = await self.get_collection_info(collection_name, self.production_client)
                    collection_point_counts[collection_name] = info.points_count
                    total_points += info.points_count
                except Exception as e:
                    log.warning(f"Could not get info for collection {collection_name}: {e}")
                    collection_point_counts[collection_name] = 0
            
            backup_progress.total_points = total_points
            
            # Backup each collection
            backup_results = []
            processed_points = 0
            
            for i, collection_name in enumerate(collections_to_backup):
                backup_progress.current_collection = collection_name
                backup_progress.completed_collections = i
                
                target_name = f"{target_prefix}{collection_name}" if target_prefix else collection_name
                
                log.info(f"Backing up collection {i+1}/{len(collections_to_backup)}: {collection_name} -> {target_name}")
                
                # Progress callback for individual collection backup
                def progress_callback(current_points, total_collection_points):
                    nonlocal processed_points
                    # Update processed points (subtract previous count for this collection, add current)
                    prev_processed = processed_points - sum(
                        collection_point_counts.get(prev_col, 0) 
                        for prev_col in collections_to_backup[:i]
                    )
                    backup_progress.processed_points = prev_processed + current_points
                
                # Backup the collection
                result = await self.backup_collection(
                    collection_name=collection_name,
                    target_name=target_name,
                    overwrite=overwrite,
                    progress_callback=progress_callback
                )
                
                backup_results.append(result)
                
                # Update processed points
                processed_points += collection_point_counts.get(collection_name, 0)
                backup_progress.processed_points = processed_points
                
                if not result["success"]:
                    backup_progress.errors.append(f"Failed to backup {collection_name}: {result.get('error', 'Unknown error')}")
                
                log.info(f"Completed {i+1}/{len(collections_to_backup)} collections")
            
            # Mark backup as completed
            backup_progress.completed_collections = len(collections_to_backup)
            backup_progress.current_collection = None
            backup_progress.status = BackupStatus.COMPLETED
            backup_progress.end_time = datetime.now(timezone.utc)
            
            # Calculate summary statistics
            successful_backups = [r for r in backup_results if r["success"]]
            failed_backups = [r for r in backup_results if not r["success"]]
            
            total_source_points = sum(r.get("source_points", 0) for r in successful_backups)
            total_target_points = sum(r.get("target_points", 0) for r in successful_backups)
            
            summary = {
                "backup_id": backup_id,
                "status": "completed",
                "total_collections": len(collections_to_backup),
                "successful_backups": len(successful_backups),
                "failed_backups": len(failed_backups),
                "total_source_points": total_source_points,
                "total_target_points": total_target_points,
                "duration_seconds": backup_progress.duration_seconds,
                "collections": backup_results,
                "errors": backup_progress.errors
            }
            
            log.info(f"Backup completed: {len(successful_backups)}/{len(collections_to_backup)} collections successful")
            return summary
            
        except Exception as e:
            # Mark backup as failed
            backup_progress.status = BackupStatus.FAILED
            backup_progress.end_time = datetime.now(timezone.utc)
            backup_progress.errors.append(str(e))
            
            log.error(f"Backup operation failed: {e}")
            
            return {
                "backup_id": backup_id,
                "status": "failed",
                "error": str(e),
                "duration_seconds": backup_progress.duration_seconds,
                "errors": backup_progress.errors
            }
    
    def _filter_collections(self, collections: List[str], filter_pattern: Optional[str]) -> List[str]:
        """
        Filter collections based on pattern matching.
        
        Args:
            collections: List of collection names
            filter_pattern: Pattern to match (supports * wildcards)
            
        Returns:
            Filtered list of collection names
        """
        if not filter_pattern:
            return collections
        
        import fnmatch
        
        filtered = [col for col in collections if fnmatch.fnmatch(col, filter_pattern)]
        log.info(f"Filtered {len(collections)} collections to {len(filtered)} using pattern '{filter_pattern}'")
        return filtered
    
    async def backup_philosophy_collections(
        self,
        target_prefix: Optional[str] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        Backup all philosophy-related collections (excludes Chat_History* collections).
        
        Args:
            target_prefix: Prefix to add to target collection names
            overwrite: Whether to overwrite existing target collections
            
        Returns:
            Dictionary with backup results and statistics
        """
        log.info("Starting backup of all philosophy collections")
        
        # Get all collections
        all_collections = await self.list_collections(self.production_client)
        
        # Filter out chat history collections
        philosophy_collections = [
            col for col in all_collections 
            if not col.startswith("Chat_History")
        ]
        
        log.info(f"Found {len(philosophy_collections)} philosophy collections (excluding {len(all_collections) - len(philosophy_collections)} chat collections)")
        
        return await self.backup_collections(
            collections=philosophy_collections,
            target_prefix=target_prefix,
            overwrite=overwrite
        )
    
    async def backup_selective_collections(
        self,
        include_patterns: List[str],
        exclude_patterns: Optional[List[str]] = None,
        target_prefix: Optional[str] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        Backup collections using include/exclude patterns.
        
        Args:
            include_patterns: Patterns for collections to include
            exclude_patterns: Patterns for collections to exclude
            target_prefix: Prefix to add to target collection names
            overwrite: Whether to overwrite existing target collections
            
        Returns:
            Dictionary with backup results and statistics
        """
        import fnmatch
        
        # Get all collections
        all_collections = await self.list_collections(self.production_client)
        
        # Apply include patterns
        included_collections = set()
        for pattern in include_patterns:
            matches = [col for col in all_collections if fnmatch.fnmatch(col, pattern)]
            included_collections.update(matches)
            log.info(f"Include pattern '{pattern}' matched {len(matches)} collections")
        
        # Apply exclude patterns
        if exclude_patterns:
            for pattern in exclude_patterns:
                excluded = [col for col in included_collections if fnmatch.fnmatch(col, pattern)]
                included_collections -= set(excluded)
                log.info(f"Exclude pattern '{pattern}' removed {len(excluded)} collections")
        
        selected_collections = list(included_collections)
        log.info(f"Selected {len(selected_collections)} collections for backup")
        
        return await self.backup_collections(
            collections=selected_collections,
            target_prefix=target_prefix,
            overwrite=overwrite
        )   
 
    async def validate_backup_integrity(
        self,
        source_collection: str,
        target_collection: str,
        sample_size: int = 100
    ) -> Dict[str, Any]:
        """
        Validate backup integrity by comparing source and target collections.
        
        Args:
            source_collection: Name of the source collection
            target_collection: Name of the target collection
            sample_size: Number of points to sample for detailed validation
            
        Returns:
            Dictionary with validation results
        """
        log.info(f"Validating backup integrity: {source_collection} -> {target_collection}")
        
        validation_result = {
            "source_collection": source_collection,
            "target_collection": target_collection,
            "valid": False,
            "checks": {},
            "errors": [],
            "warnings": []
        }
        
        try:
            # Check if both collections exist
            source_exists = await self.collection_exists(source_collection, self.production_client)
            target_exists = await self.collection_exists(target_collection, self.local_client)
            
            validation_result["checks"]["source_exists"] = source_exists
            validation_result["checks"]["target_exists"] = target_exists
            
            if not source_exists:
                validation_result["errors"].append(f"Source collection '{source_collection}' does not exist")
                return validation_result
            
            if not target_exists:
                validation_result["errors"].append(f"Target collection '{target_collection}' does not exist")
                return validation_result
            
            # Get collection information
            source_info = await self.get_collection_info(source_collection, self.production_client)
            target_info = await self.get_collection_info(target_collection, self.local_client)
            
            # Validate point counts
            point_count_match = source_info.points_count == target_info.points_count
            validation_result["checks"]["point_count_match"] = point_count_match
            validation_result["checks"]["source_points"] = source_info.points_count
            validation_result["checks"]["target_points"] = target_info.points_count
            
            if not point_count_match:
                validation_result["errors"].append(
                    f"Point count mismatch: source={source_info.points_count}, target={target_info.points_count}"
                )
            
            # Validate collection configuration
            config_match = await self._validate_collection_config(source_info.config, target_info.config)
            validation_result["checks"]["config_match"] = config_match
            
            if not config_match:
                validation_result["warnings"].append("Collection configurations differ")
            
            # Sample-based validation
            if source_info.points_count > 0 and target_info.points_count > 0:
                sample_validation = await self._validate_sample_points(
                    source_collection, target_collection, min(sample_size, source_info.points_count)
                )
                validation_result["checks"]["sample_validation"] = sample_validation
                
                if not sample_validation["valid"]:
                    validation_result["errors"].extend(sample_validation["errors"])
            
            # Overall validation result
            validation_result["valid"] = (
                point_count_match and 
                len(validation_result["errors"]) == 0
            )
            
            if validation_result["valid"]:
                log.info(f"Backup integrity validation passed for {source_collection} -> {target_collection}")
            else:
                log.warning(f"Backup integrity validation failed for {source_collection} -> {target_collection}")
            
            return validation_result
            
        except Exception as e:
            validation_result["errors"].append(f"Validation failed with exception: {str(e)}")
            log.error(f"Backup integrity validation error: {e}")
            return validation_result
    
    async def _validate_collection_config(self, source_config: Dict[str, Any], target_config: Dict[str, Any]) -> bool:
        """
        Validate that collection configurations are compatible.
        
        Args:
            source_config: Source collection configuration
            target_config: Target collection configuration
            
        Returns:
            True if configurations are compatible
        """
        try:
            # Extract key configuration parameters
            source_params = source_config.get("params", {})
            target_params = target_config.get("params", {})
            
            # Check vector configurations
            source_vectors = source_params.get("vectors", {})
            target_vectors = target_params.get("vectors", {})
            
            # Compare vector dimensions and distance metrics
            if isinstance(source_vectors, dict) and isinstance(target_vectors, dict):
                for vector_name, source_vector_config in source_vectors.items():
                    if vector_name not in target_vectors:
                        log.warning(f"Vector '{vector_name}' missing in target configuration")
                        return False
                    
                    target_vector_config = target_vectors[vector_name]
                    
                    if source_vector_config.get("size") != target_vector_config.get("size"):
                        log.warning(f"Vector size mismatch for '{vector_name}'")
                        return False
                    
                    if source_vector_config.get("distance") != target_vector_config.get("distance"):
                        log.warning(f"Distance metric mismatch for '{vector_name}'")
                        return False
            
            return True
            
        except Exception as e:
            log.error(f"Configuration validation error: {e}")
            return False
    
    async def _validate_sample_points(
        self,
        source_collection: str,
        target_collection: str,
        sample_size: int
    ) -> Dict[str, Any]:
        """
        Validate a sample of points between source and target collections.
        
        Args:
            source_collection: Source collection name
            target_collection: Target collection name
            sample_size: Number of points to sample
            
        Returns:
            Dictionary with sample validation results
        """
        validation_result = {
            "valid": True,
            "sampled_points": 0,
            "matching_points": 0,
            "errors": []
        }
        
        try:
            # Get sample points from source
            source_scroll = await self.execute_with_retries(
                lambda: self.production_client.scroll(
                    collection_name=source_collection,
                    limit=sample_size,
                    with_payload=True,
                    with_vectors=False  # Skip vectors for performance
                ),
                operation_name=f"Sample points from {source_collection}"
            )
            
            if not source_scroll.points:
                validation_result["errors"].append("No points found in source collection for sampling")
                validation_result["valid"] = False
                return validation_result
            
            validation_result["sampled_points"] = len(source_scroll.points)
            
            # Check if corresponding points exist in target
            matching_count = 0
            
            for point in source_scroll.points:
                try:
                    target_point = await self.execute_with_retries(
                        lambda: self.local_client.retrieve(
                            collection_name=target_collection,
                            ids=[point.id],
                            with_payload=True,
                            with_vectors=False
                        ),
                        operation_name=f"Retrieve point {point.id} from {target_collection}"
                    )
                    
                    if target_point and len(target_point) > 0:
                        # Compare payloads
                        if point.payload == target_point[0].payload:
                            matching_count += 1
                        else:
                            validation_result["errors"].append(f"Payload mismatch for point {point.id}")
                    else:
                        validation_result["errors"].append(f"Point {point.id} not found in target collection")
                        
                except Exception as e:
                    validation_result["errors"].append(f"Error validating point {point.id}: {str(e)}")
            
            validation_result["matching_points"] = matching_count
            
            # Consider validation successful if at least 95% of sampled points match
            match_ratio = matching_count / len(source_scroll.points)
            validation_result["match_ratio"] = match_ratio
            
            if match_ratio < 0.95:
                validation_result["valid"] = False
                validation_result["errors"].append(f"Low match ratio: {match_ratio:.2%}")
            
            return validation_result
            
        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Sample validation failed: {str(e)}")
            return validation_result
    
    async def retry_failed_backup(
        self,
        backup_id: str,
        retry_failed_only: bool = True
    ) -> Dict[str, Any]:
        """
        Retry a failed backup operation.
        
        Args:
            backup_id: ID of the backup to retry
            retry_failed_only: If True, only retry failed collections
            
        Returns:
            Dictionary with retry results
        """
        backup_progress = self.get_backup_progress(backup_id)
        
        if not backup_progress:
            raise ValueError(f"Backup {backup_id} not found")
        
        if backup_progress.status not in [BackupStatus.FAILED, BackupStatus.COMPLETED]:
            raise ValueError(f"Backup {backup_id} is not in a retryable state (status: {backup_progress.status})")
        
        log.info(f"Retrying backup {backup_id} (retry_failed_only={retry_failed_only})")
        
        # This would require storing the original backup parameters
        # For now, return an error indicating this feature needs the original parameters
        return {
            "backup_id": backup_id,
            "status": "error",
            "message": "Retry functionality requires storing original backup parameters. Please start a new backup operation."
        }
    
    async def repair_collection(
        self,
        source_collection: str,
        target_collection: str,
        repair_mode: str = "missing_points"
    ) -> Dict[str, Any]:
        """
        Repair a target collection by syncing missing or corrupted data.
        
        Args:
            source_collection: Source collection name
            target_collection: Target collection name
            repair_mode: Type of repair ("missing_points", "full_sync")
            
        Returns:
            Dictionary with repair results
        """
        log.info(f"Starting collection repair: {source_collection} -> {target_collection} (mode: {repair_mode})")
        
        repair_result = {
            "source_collection": source_collection,
            "target_collection": target_collection,
            "repair_mode": repair_mode,
            "success": False,
            "repaired_points": 0,
            "errors": []
        }
        
        try:
            # Validate collections exist
            if not await self.collection_exists(source_collection, self.production_client):
                repair_result["errors"].append(f"Source collection '{source_collection}' does not exist")
                return repair_result
            
            if not await self.collection_exists(target_collection, self.local_client):
                repair_result["errors"].append(f"Target collection '{target_collection}' does not exist")
                return repair_result
            
            if repair_mode == "missing_points":
                # Find and sync missing points
                repaired_count = await self._repair_missing_points(source_collection, target_collection)
                repair_result["repaired_points"] = repaired_count
                
            elif repair_mode == "full_sync":
                # Full resync (essentially a backup with overwrite)
                backup_result = await self.backup_collection(
                    collection_name=source_collection,
                    target_name=target_collection,
                    overwrite=True
                )
                repair_result["success"] = backup_result["success"]
                repair_result["repaired_points"] = backup_result.get("processed_points", 0)
                if not backup_result["success"]:
                    repair_result["errors"].append(backup_result.get("error", "Full sync failed"))
                
            else:
                repair_result["errors"].append(f"Unknown repair mode: {repair_mode}")
                return repair_result
            
            repair_result["success"] = len(repair_result["errors"]) == 0
            
            if repair_result["success"]:
                log.info(f"Collection repair completed: {repair_result['repaired_points']} points repaired")
            else:
                log.error(f"Collection repair failed: {repair_result['errors']}")
            
            return repair_result
            
        except Exception as e:
            repair_result["errors"].append(f"Repair operation failed: {str(e)}")
            log.error(f"Collection repair error: {e}")
            return repair_result
    
    async def _repair_missing_points(self, source_collection: str, target_collection: str) -> int:
        """
        Repair collection by performing a full backup (incremental repair not yet implemented).

        NOTE: This currently performs a full backup with overwrite instead of incremental
        point-by-point synchronization. True incremental repair (syncing only missing points)
        requires comparing point IDs between source and target collections, which is
        planned for a future release.

        For incremental repair, consider:
        1. Using snapshot-based backup (much faster for full collection sync)
        2. Implementing custom point ID comparison logic if needed
        3. Using Qdrant's collection aliases for zero-downtime updates

        Args:
            source_collection: Source collection name
            target_collection: Target collection name

        Returns:
            Number of points processed in full backup operation
        """
        log.info(
            f"Performing full backup repair for '{target_collection}' "
            "(incremental point-by-point repair not yet implemented)"
        )

        # Fall back to full backup - this ensures consistency but is not optimal
        # for large collections where only a few points differ
        backup_result = await self.backup_collection(
            collection_name=source_collection,
            target_name=target_collection,
            overwrite=True
        )

        return backup_result.get("processed_points", 0)

    async def backup_collection_snapshot(
        self,
        collection_name: str,
        target_name: Optional[str] = None,
        overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        Backup a collection using Qdrant's snapshot API (recommended method).

        This method is more efficient and reliable than point-by-point backup as it:
        - Handles all vector configurations automatically (including sparse vectors)
        - Preserves exact collection settings
        - Is much faster for large collections

        Args:
            collection_name: Name of the source collection
            target_name: Name for the target collection (defaults to source name)
            overwrite: Whether to overwrite existing target collection

        Returns:
            Dictionary with backup results and statistics
        """
        target_name = target_name or collection_name

        log.info(f"Starting snapshot-based backup of collection '{collection_name}' to '{target_name}'")

        try:
            # Use extracted validation logic
            await self._validate_and_prepare_backup(collection_name, target_name, overwrite)

            # Create snapshot on production
            log.info(f"Creating snapshot of '{collection_name}' on production")
            snapshot_info = await self.execute_with_retries(
                lambda: self.production_client.create_snapshot(collection_name=collection_name),
                operation_name=f"Create snapshot of {collection_name}"
            )

            snapshot_name = snapshot_info.name
            log.info(f"Created snapshot: {snapshot_name}")

            try:
                # Download snapshot to temporary file
                import tempfile
                import httpx

                with tempfile.NamedTemporaryFile(delete=False, suffix=".snapshot") as temp_file:
                    snapshot_file = temp_file.name

                    log.info(f"Downloading snapshot {snapshot_name}")

                    # Build download URL
                    prod_url = self.production_config["url"]
                    download_url = f"{prod_url}/collections/{collection_name}/snapshots/{snapshot_name}"

                    # Download snapshot with authentication
                    headers = {}
                    api_key_env = self.production_config.get("api_key_env")
                    if api_key_env:
                        api_key = os.environ.get(api_key_env)
                        if api_key:
                            headers["api-key"] = api_key

                    async with httpx.AsyncClient(timeout=600.0) as client:
                        response = await client.get(download_url, headers=headers)
                        response.raise_for_status()

                        temp_file.write(response.content)
                        temp_file.flush()

                    log.info(f"Downloaded snapshot to {snapshot_file}")

                    # Upload and recover snapshot on local
                    log.info(f"Recovering collection '{target_name}' from snapshot on local")

                    # Read snapshot file
                    with open(snapshot_file, 'rb') as f:
                        snapshot_data = f.read()

                    # Upload and recover snapshot (single operation)
                    local_url = self.local_config["url"]
                    upload_url = f"{local_url}/collections/{target_name}/snapshots/upload"

                    # Upload snapshot with recovery
                    async with httpx.AsyncClient(timeout=600.0) as client:
                        upload_response = await client.post(
                            upload_url,
                            params={"wait": "true"},
                            files={"snapshot": ("snapshot.snapshot", snapshot_data, "application/octet-stream")}
                        )
                        upload_response.raise_for_status()

                    log.info(f"Successfully recovered collection '{target_name}' from snapshot")

                    # Clean up temp file
                    import os as os_module
                    os_module.unlink(snapshot_file)

                # Verify backup
                target_info = await self.get_collection_info(target_name, self.local_client)
                source_info = await self.get_collection_info(collection_name, self.production_client)

                backup_result = {
                    "source_collection": collection_name,
                    "target_collection": target_name,
                    "source_points": source_info.points_count,
                    "target_points": target_info.points_count,
                    "success": True,
                    "method": "snapshot"
                }

                log.info(f"Snapshot backup completed: {source_info.points_count} -> {target_info.points_count} points")
                return backup_result

            finally:
                # Clean up snapshot from production
                try:
                    log.info(f"Deleting snapshot {snapshot_name} from production")
                    await self.execute_with_retries(
                        lambda: self.production_client.delete_snapshot(
                            collection_name=collection_name,
                            snapshot_name=snapshot_name
                        ),
                        operation_name=f"Delete snapshot {snapshot_name}"
                    )
                except Exception as cleanup_error:
                    log.warning(f"Failed to clean up snapshot: {cleanup_error}")

        except Exception as e:
            log.error(f"Snapshot backup failed for collection '{collection_name}': {e}")
            return {
                "source_collection": collection_name,
                "target_collection": target_name,
                "success": False,
                "error": str(e),
                "method": "snapshot"
            }