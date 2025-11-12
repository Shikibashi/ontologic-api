# app/router/chat_config.py
"""
Chat history configuration and management API endpoints.
Provides endpoints for viewing configuration and managing data retention.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from pydantic import BaseModel, Field

from app.core.chat_dependencies import (
    get_feature_flags,
    get_chat_config,
    require_chat_history_enabled
)
from app.services.feature_flags import FeatureFlagService
from app.services.chat_config import ChatHistoryConfig
from app.services.chat_cleanup import ChatCleanupService
from app.core.constants import CLEANUP_SAFETY_THRESHOLD
from app.core.error_responses import (
    create_validation_error,
    create_service_unavailable_error,
    create_internal_error
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/config", tags=["chat-config"])

class CleanupStatsResponse(BaseModel):
    """Response model for cleanup statistics."""
    retention_days: int
    cutoff_date: str
    expired_conversations: int
    expired_messages: int
    estimated_qdrant_points: int
    error: Optional[str] = None

class CleanupResultResponse(BaseModel):
    """Response model for cleanup operation results."""
    status: str
    cutoff_date: Optional[str] = None
    retention_days: Optional[int] = None
    conversations_deleted: int = 0
    messages_deleted: int = 0
    qdrant_points_deleted: int = 0
    errors: list = Field(default_factory=list)

class SessionCleanupResponse(BaseModel):
    """Response model for session cleanup results."""
    status: str
    session_id: str
    conversations_deleted: int = 0
    messages_deleted: int = 0
    qdrant_points_deleted: int = 0
    errors: list = Field(default_factory=list)

@router.get("/status", summary="Get chat history feature status")
async def get_chat_status(
    request: Request,
    feature_flags: FeatureFlagService = Depends(get_feature_flags),
    chat_config: ChatHistoryConfig = Depends(get_chat_config)
) -> Dict[str, Any]:
    """
    Get the current status and configuration of the chat history feature.

    Returns:
        Dictionary with feature status and configuration details
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        if not feature_flags:
            error = create_service_unavailable_error(
                service="feature flags",
                message="Feature flags service not available",
                request_id=request_id
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        feature_status = feature_flags.get_chat_history_status()

        if feature_status["enabled"]:
            if not chat_config:
                error = create_service_unavailable_error(
                    service="chat config",
                    message="Chat config service not available",
                    request_id=request_id
                )
                raise HTTPException(status_code=503, detail=error.model_dump())
            config_summary = chat_config.get_config_summary()
            return {
                "feature": feature_status,
                "configuration": config_summary
            }
        else:
            return {
                "feature": feature_status,
                "configuration": {}
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_chat_status: {e}")
        error = create_internal_error(
            message=f"Chat config error: {str(e)}",
            error_type="config_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())

@router.get("/cleanup/stats", summary="Get cleanup statistics")
async def get_cleanup_stats(
    request: Request,
    _: bool = Depends(require_chat_history_enabled),
    feature_flags: FeatureFlagService = Depends(get_feature_flags),
    chat_config: ChatHistoryConfig = Depends(get_chat_config)
) -> Dict[str, Any]:
    """
    Get statistics about data that would be cleaned up based on retention policy.
    This is a dry run that shows what cleanup would delete without actually deleting anything.

    Returns:
        Statistics about expired data
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        if not feature_flags or not chat_config:
            error = create_service_unavailable_error(
                service="chat history",
                message="Service dependencies not available",
                request_id=request_id
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        # Simple stats without complex cleanup service
        retention_days = chat_config.get_retention_days()
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()

        return {
            "retention_days": retention_days,
            "cutoff_date": cutoff_date,
            "expired_conversations": 0,  # Would need database query
            "expired_messages": 0,       # Would need database query
            "estimated_qdrant_points": 0, # Would need Qdrant query
            "error": None,
            "note": "Detailed stats require database connection"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_cleanup_stats: {e}")
        error = create_internal_error(
            message=f"Cleanup stats error: {str(e)}",
            error_type="cleanup_stats_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())

@router.post("/cleanup/run", response_model=CleanupResultResponse, summary="Run cleanup operation")
async def run_cleanup(
    request: Request,
    force: bool = Query(False, description="Skip safety checks and run cleanup immediately"),
    _: bool = Depends(require_chat_history_enabled),
    feature_flags: FeatureFlagService = Depends(get_feature_flags),
    chat_config: ChatHistoryConfig = Depends(get_chat_config)
) -> CleanupResultResponse:
    """
    Run the cleanup operation to remove expired chat history data.
    
    **WARNING**: This operation permanently deletes data and cannot be undone.
    
    Args:
        force: If True, skip safety checks and run cleanup immediately
        
    Returns:
        Results of the cleanup operation
    """
    if not force:
        # Get stats first to show what would be deleted
        cleanup_service = ChatCleanupService(chat_config, feature_flags)
        stats = await cleanup_service.get_cleanup_stats()

        if stats.get("expired_conversations", 0) > CLEANUP_SAFETY_THRESHOLD:
            error = create_validation_error(
                field="force",
                message=f"Cleanup would delete {stats['expired_conversations']} conversations (threshold: {CLEANUP_SAFETY_THRESHOLD}). Use force=true to proceed.",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error.model_dump()
            )
    
    cleanup_service = ChatCleanupService(chat_config, feature_flags)
    result = await cleanup_service.cleanup_expired_sessions()
    
    return CleanupResultResponse(**result)

@router.delete("/session/{session_id}", response_model=SessionCleanupResponse, summary="Delete session data")
async def delete_session_data(
    session_id: str,
    _: bool = Depends(require_chat_history_enabled),
    feature_flags: FeatureFlagService = Depends(get_feature_flags),
    chat_config: ChatHistoryConfig = Depends(get_chat_config)
) -> SessionCleanupResponse:
    """
    Delete all chat history data for a specific session.
    
    **WARNING**: This operation permanently deletes all conversation data for the session.
    
    Args:
        session_id: The session ID to delete data for
        
    Returns:
        Results of the deletion operation
    """
    cleanup_service = ChatCleanupService(chat_config, feature_flags)
    result = await cleanup_service.cleanup_session_data(session_id)
    
    return SessionCleanupResponse(**result)

@router.get("/environment", summary="Get environment-specific configuration")
async def get_environment_config(
    request: Request,
    feature_flags: FeatureFlagService = Depends(get_feature_flags),
    chat_config: ChatHistoryConfig = Depends(get_chat_config)
) -> Dict[str, Any]:
    """
    Get environment-specific configuration details.

    Returns:
        Environment configuration including collection names and settings
    """
    request_id = getattr(request.state, 'request_id', None)

    try:
        if not feature_flags:
            error = create_service_unavailable_error(
                service="feature flags",
                message="Feature flags service not available",
                request_id=request_id
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        if not chat_config:
            error = create_service_unavailable_error(
                service="chat config",
                message="Chat config service not available",
                request_id=request_id
            )
            raise HTTPException(status_code=503, detail=error.model_dump())

        if not feature_flags.is_chat_history_enabled():
            return {
                "enabled": False,
                "environment": chat_config.env,
                "message": "Chat history feature is disabled"
            }

        return {
            "enabled": True,
            "environment": chat_config.env,
            "collection_name": chat_config.get_chat_collection_name(),
            "qdrant_config": {
                "local": chat_config.get_local_qdrant_config(),
                "production": {
                    "url": chat_config.get_production_qdrant_config()["url"],
                    "timeout": chat_config.get_production_qdrant_config()["timeout"],
                    "collection_name": chat_config.get_production_qdrant_config()["collection_name"]
                    # Note: API key is not included for security
                }
            },
            "retention_policy": {
                "retention_days": chat_config.get_retention_days(),
                "cleanup_batch_size": chat_config.get_cleanup_batch_size(),
                "vector_upload_batch_size": chat_config.get_vector_upload_batch_size()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_environment_config: {e}")
        error = create_internal_error(
            message=f"Environment config error: {str(e)}",
            error_type="config_error",
            request_id=request_id
        )
        raise HTTPException(status_code=500, detail=error.model_dump())