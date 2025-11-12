"""
FastAPI router for Qdrant backup operations.

This router provides API endpoints for managing Qdrant collection backups
from production to local development environments.
"""

import os
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.core.backup_models import (
    BackupRequest, BackupResponse, BackupProgressResponse,
    ValidationRequest, ValidationResponse, RepairRequest, RepairResponse,
    CollectionInfoResponse, CollectionListResponse
)
from app.services.qdrant_backup_service import QdrantBackupService
from app.core.logger import log
from app.core.error_responses import (
    create_validation_error,
    create_not_found_error,
    create_internal_error,
    create_service_unavailable_error
)


# Create router
backup_router = APIRouter(prefix="/admin/backup", tags=["backup"])

# Global backup service instance (will be initialized on first use)
_backup_service: Optional[QdrantBackupService] = None


def get_backup_service(request: Request) -> QdrantBackupService:
    """
    Dependency to get or create the backup service instance.

    Returns:
        QdrantBackupService instance

    Raises:
        HTTPException: If required environment variables are missing
    """
    global _backup_service

    if _backup_service is None:
        # Check for required environment variables
        api_key = os.environ.get("QDRANT_API_KEY")
        if not api_key:
            error = create_service_unavailable_error(
                service="Backup service",
                message="QDRANT_API_KEY environment variable is required for backup operations",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        # Production Qdrant configuration
        production_config = {
            "url": os.environ.get("QDRANT_PRODUCTION_URL", "https://qdrant.ontologicai.com"),
            "api_key_env": "QDRANT_API_KEY",
            "timeout": 30,
            "retry_attempts": 3,
            "backup_batch_size": 1000
        }

        # Local Qdrant configuration
        local_config = {
            "url": os.environ.get("QDRANT_LOCAL_URL", "http://127.0.0.1:6333"),
            "api_key_env": "QDRANT_LOCAL_API_KEY",  # Optional for local
            "timeout": 30,
            "retry_attempts": 3
        }

        try:
            _backup_service = QdrantBackupService(production_config, local_config)
            log.info("Backup service initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize backup service: {e}")
            error = create_internal_error(
                message=f"Backup service initialization failed: {str(e)}",
                error_type="initialization_error",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=500, detail=error.model_dump())

    return _backup_service


@backup_router.get("/health")
async def backup_health_check(
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Check the health of backup service connections.

    Returns:
        Health status of production and local Qdrant connections
    """
    try:
        production_valid, local_valid = await backup_service.validate_connections()

        return {
            "status": "healthy" if (production_valid and local_valid) else "degraded",
            "production_connection": "healthy" if production_valid else "failed",
            "local_connection": "healthy" if local_valid else "failed",
            "service_ready": production_valid and local_valid
        }
    except Exception as e:
        log.error(f"Backup health check failed: {e}")
        error = create_internal_error(
            message=f"Health check failed: {str(e)}",
            error_type="health_check_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.get("/collections/production", response_model=CollectionListResponse)
async def list_production_collections(
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    List all collections in the production Qdrant instance.

    Returns:
        List of collection names in production
    """
    try:
        collections = await backup_service.list_collections(backup_service.production_client)
        return CollectionListResponse(
            collections=collections,
            total_count=len(collections),
            source="production"
        )
    except Exception as e:
        log.error(f"Failed to list production collections: {e}")
        error = create_internal_error(
            message=f"Failed to list production collections: {str(e)}",
            error_type="collection_list_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.get("/collections/local", response_model=CollectionListResponse)
async def list_local_collections(
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    List all collections in the local Qdrant instance.

    Returns:
        List of collection names in local instance
    """
    try:
        collections = await backup_service.list_collections(backup_service.local_client)
        return CollectionListResponse(
            collections=collections,
            total_count=len(collections),
            source="local"
        )
    except Exception as e:
        log.error(f"Failed to list local collections: {e}")
        error = create_internal_error(
            message=f"Failed to list local collections: {str(e)}",
            error_type="collection_list_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.get("/collections/production/{collection_name}/info", response_model=CollectionInfoResponse)
async def get_production_collection_info(
    collection_name: str,
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Get detailed information about a production collection.

    Args:
        collection_name: Name of the collection

    Returns:
        Detailed collection information
    """
    try:
        info = await backup_service.get_collection_info(collection_name, backup_service.production_client)
        return CollectionInfoResponse(
            name=info.name,
            vectors_count=info.vectors_count,
            indexed_vectors_count=info.indexed_vectors_count,
            points_count=info.points_count,
            segments_count=info.segments_count,
            config=info.config,
            payload_schema=info.payload_schema
        )
    except Exception as e:
        log.error(f"Failed to get production collection info for {collection_name}: {e}")
        error = create_internal_error(
            message=f"Failed to get collection info: {str(e)}",
            error_type="collection_info_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.get("/collections/local/{collection_name}/info", response_model=CollectionInfoResponse)
async def get_local_collection_info(
    collection_name: str,
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Get detailed information about a local collection.

    Args:
        collection_name: Name of the collection

    Returns:
        Detailed collection information
    """
    try:
        info = await backup_service.get_collection_info(collection_name, backup_service.local_client)
        return CollectionInfoResponse(
            name=info.name,
            vectors_count=info.vectors_count,
            indexed_vectors_count=info.indexed_vectors_count,
            points_count=info.points_count,
            segments_count=info.segments_count,
            config=info.config,
            payload_schema=info.payload_schema
        )
    except Exception as e:
        log.error(f"Failed to get local collection info for {collection_name}: {e}")
        error = create_internal_error(
            message=f"Failed to get collection info: {str(e)}",
            error_type="collection_info_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


async def run_backup_task(backup_service: QdrantBackupService, request: BackupRequest) -> str:
    """
    Background task to run backup operation.
    
    Args:
        backup_service: Backup service instance
        request: Backup request parameters
        
    Returns:
        Backup ID
    """
    try:
        if request.include_patterns:
            # Selective backup with patterns
            result = await backup_service.backup_selective_collections(
                include_patterns=request.include_patterns,
                exclude_patterns=request.exclude_patterns,
                target_prefix=request.target_prefix,
                overwrite=request.overwrite
            )
        elif request.collections:
            # Specific collections backup
            result = await backup_service.backup_collections(
                collections=request.collections,
                target_prefix=request.target_prefix,
                overwrite=request.overwrite
            )
        else:
            # All philosophy collections backup
            result = await backup_service.backup_philosophy_collections(
                target_prefix=request.target_prefix,
                overwrite=request.overwrite
            )
        
        log.info(f"Backup task completed: {result.get('backup_id')}")
        return result.get("backup_id")
        
    except Exception as e:
        log.error(f"Backup task failed: {e}")
        raise


@backup_router.post("/start", response_model=Dict[str, str])
async def start_backup(
    backup_request: BackupRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Start a backup operation in the background.

    Args:
        backup_request: Backup configuration
        background_tasks: FastAPI background tasks

    Returns:
        Backup ID for tracking progress
    """
    try:
        # Validate connections before starting backup
        production_valid, local_valid = await backup_service.validate_connections()

        if not production_valid:
            error = create_service_unavailable_error(
                service="Production Qdrant",
                message="Production Qdrant connection is not available",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        if not local_valid:
            error = create_service_unavailable_error(
                service="Local Qdrant",
                message="Local Qdrant connection is not available",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        # Create a temporary progress tracker to get backup ID
        collections_to_backup = backup_request.collections or []
        if not collections_to_backup and not backup_request.include_patterns:
            # Will backup all philosophy collections
            all_collections = await backup_service.list_collections(backup_service.production_client)
            collections_to_backup = [col for col in all_collections if not col.startswith("Chat_History")]

        progress = backup_service.create_backup_progress(collections_to_backup)
        backup_id = progress.backup_id

        # Start backup in background
        background_tasks.add_task(run_backup_task, backup_service, backup_request)

        log.info(f"Started backup operation {backup_id}")

        return {
            "backup_id": backup_id,
            "status": "started",
            "message": f"Backup operation started with ID {backup_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to start backup: {e}")
        error = create_internal_error(
            message=f"Failed to start backup: {str(e)}",
            error_type="backup_start_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.get("/status/{backup_id}", response_model=BackupProgressResponse)
async def get_backup_status(
    backup_id: str,
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Get the status of a backup operation.

    Args:
        backup_id: Backup operation ID

    Returns:
        Current backup progress and status
    """
    try:
        progress = backup_service.get_backup_progress(backup_id)

        if not progress:
            error = create_not_found_error(
                resource="Backup",
                identifier=backup_id,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        return BackupProgressResponse(
            backup_id=progress.backup_id,
            status=progress.status,
            total_collections=progress.total_collections,
            completed_collections=progress.completed_collections,
            current_collection=progress.current_collection,
            total_points=progress.total_points,
            processed_points=progress.processed_points,
            collection_progress_percent=progress.collection_progress_percent,
            point_progress_percent=progress.point_progress_percent,
            start_time=progress.start_time,
            end_time=progress.end_time,
            duration_seconds=progress.duration_seconds,
            errors=progress.errors
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get backup status for {backup_id}: {e}")
        error = create_internal_error(
            message=f"Failed to get backup status: {str(e)}",
            error_type="backup_status_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.post("/validate", response_model=ValidationResponse)
async def validate_backup(
    validation_request: ValidationRequest,
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Validate backup integrity between source and target collections.

    Args:
        validation_request: Validation parameters

    Returns:
        Validation results
    """
    try:
        result = await backup_service.validate_backup_integrity(
            source_collection=validation_request.source_collection,
            target_collection=validation_request.target_collection,
            sample_size=validation_request.sample_size
        )

        # Convert result to response model
        return ValidationResponse(
            source_collection=result["source_collection"],
            target_collection=result["target_collection"],
            valid=result["valid"],
            checks=result["checks"],
            errors=result["errors"],
            warnings=result["warnings"]
        )

    except Exception as e:
        log.error(f"Backup validation failed: {e}")
        error = create_internal_error(
            message=f"Validation failed: {str(e)}",
            error_type="validation_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.post("/repair", response_model=RepairResponse)
async def repair_collection(
    repair_request: RepairRequest,
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Repair a target collection by syncing with source.

    Args:
        repair_request: Repair parameters

    Returns:
        Repair operation results
    """
    try:
        result = await backup_service.repair_collection(
            source_collection=repair_request.source_collection,
            target_collection=repair_request.target_collection,
            repair_mode=repair_request.repair_mode
        )

        return RepairResponse(
            source_collection=result["source_collection"],
            target_collection=result["target_collection"],
            repair_mode=result["repair_mode"],
            success=result["success"],
            repaired_points=result["repaired_points"],
            errors=result["errors"]
        )

    except Exception as e:
        log.error(f"Collection repair failed: {e}")
        error = create_internal_error(
            message=f"Repair failed: {str(e)}",
            error_type="repair_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())


@backup_router.delete("/collections/local/{collection_name}")
async def delete_local_collection(
    collection_name: str,
    request: Request,
    backup_service: QdrantBackupService = Depends(get_backup_service)
):
    """
    Delete a collection from the local Qdrant instance.

    Args:
        collection_name: Name of the collection to delete

    Returns:
        Deletion confirmation
    """
    try:
        # Check if collection exists
        if not await backup_service.collection_exists(collection_name, backup_service.local_client):
            error = create_not_found_error(
                resource="Collection",
                identifier=collection_name,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=404, detail=error.model_dump())

        # Delete the collection
        await backup_service.execute_with_retries(
            lambda: backup_service.local_client.delete_collection(collection_name),
            operation_name=f"Delete local collection {collection_name}"
        )

        log.info(f"Deleted local collection: {collection_name}")

        return {
            "collection_name": collection_name,
            "status": "deleted",
            "message": f"Collection '{collection_name}' deleted from local instance"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to delete local collection {collection_name}: {e}")
        error = create_internal_error(
            message=f"Failed to delete collection: {str(e)}",
            error_type="collection_delete_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(status_code=500, detail=error.model_dump())