"""
Chat History Health Check API Router.

This module provides health check endpoints for monitoring the chat history
system components including database, vector store, and privacy compliance.
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from datetime import datetime, timezone

from app.core.dependencies import QdrantManagerDep
from app.core.logger import log
from app.services.chat_monitoring import chat_monitoring
from app.services.chat_qdrant_service import ChatQdrantService
from app.config.settings import get_settings
from app.core.error_responses import (
    create_internal_error,
    create_service_unavailable_error
)


router = APIRouter(prefix="/chat/health", tags=["Chat Health"])


def _get_environment_collection_name_fallback() -> str:
    """
    Fallback function to get environment-specific collection name without service instance.
    
    Returns:
        Environment-specific collection name:
        - Production: "Chat_History"
        - Development: "Chat_History_Dev" 
        - Testing: "Chat_History_Test"
    """
    import os
    app_env = os.environ.get("APP_ENV", "dev").lower()
    
    if app_env == "prod":
        return "Chat_History"
    elif app_env == "test":
        return "Chat_History_Test"
    else:
        return "Chat_History_Dev"


def is_chat_history_enabled() -> bool:
    """Check if chat history feature is enabled in configuration."""
    settings = get_settings()
    return settings.chat_history


@router.get("/status", summary="Get overall chat system health status")
async def get_chat_health_status(
    request: Request,
    qdrant_manager: QdrantManagerDep = None
) -> Dict[str, Any]:
    """
    Get comprehensive health status of the chat history system.
    
    Returns:
        Dictionary with health status of all chat components
    """
    if not is_chat_history_enabled():
        return {
            "status": "disabled",
            "message": "Chat history feature is disabled",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {}
        }
    
    try:
        # Get Qdrant client and collection name
        qdrant_client = qdrant_manager.qclient if qdrant_manager else None
        if qdrant_client:
            # Get the service from app state to call the method
            chat_qdrant_service = getattr(request.app.state, 'chat_qdrant_service', None)
            if chat_qdrant_service:
                collection_name = chat_qdrant_service._get_environment_collection_name()
            else:
                # Fallback to determine collection name without service
                collection_name = _get_environment_collection_name_fallback()
        else:
            collection_name = "Chat_History"
        
        # Run comprehensive health check
        health_results = await chat_monitoring.run_comprehensive_health_check(
            qdrant_client=qdrant_client,
            collection_name=collection_name
        )
        
        return health_results
        
    except Exception as e:
        log.error(f"Chat health check failed: {e}")
        return {
            "status": "error",
            "message": f"Health check failed: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }


@router.get("/database", summary="Get database health status")
async def get_database_health(request: Request) -> Dict[str, Any]:
    """
    Get PostgreSQL database health status for chat history.

    Returns:
        Database health check results
    """
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat_history",
            message="Chat history feature is not enabled",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )

    try:
        health_result = await chat_monitoring.check_database_health()
        return health_result.to_dict()

    except Exception as e:
        log.error(f"Database health check failed: {e}")
        error = create_internal_error(
            message=f"Database health check failed: {str(e)}",
            error_type="database_health_check_failed",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=500,
            detail=error.model_dump()
        )


@router.get("/qdrant", summary="Get Qdrant vector database health status")
async def get_qdrant_health(
    request: Request,
    qdrant_manager: QdrantManagerDep = None
) -> Dict[str, Any]:
    """
    Get Qdrant vector database health status for chat history.

    Returns:
        Qdrant health check results
    """
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat_history",
            message="Chat history feature is not enabled",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )

    if not qdrant_manager:
        error = create_service_unavailable_error(
            service="qdrant",
            message="Qdrant service not available",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )
    
    try:
        # Get collection name safely
        settings = get_settings()
        env = getattr(settings, 'env', 'dev')
        collection_name = f"Chat_History_{env.title()}" if env != 'prod' else "Chat_History"
        
        # Simple health check without complex monitoring
        try:
            collections = await qdrant_manager.get_collections()
            collection_names = [c.name for c in collections.collections]
            collection_exists = collection_name in collection_names
            
            return {
                "status": "healthy" if collection_exists else "collection_missing",
                "collection_name": collection_name,
                "collection_exists": collection_exists,
                "total_collections": len(collection_names),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as qdrant_error:
            return {
                "status": "unhealthy",
                "collection_name": collection_name,
                "error": str(qdrant_error),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
    except Exception as e:
        log.error(f"Qdrant health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@router.get("/errors", summary="Get error rate and statistics")
async def get_error_statistics(request: Request) -> Dict[str, Any]:
    """
    Get error statistics and rates for chat operations.

    Returns:
        Error statistics and health status
    """
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat_history",
            message="Chat history feature is not enabled",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )

    try:
        error_health = chat_monitoring.check_error_rates()
        return error_health.to_dict()

    except Exception as e:
        log.error(f"Error statistics check failed: {e}")
        error = create_internal_error(
            message=f"Error statistics check failed: {str(e)}",
            error_type="error_statistics_check_failed",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=500,
            detail=error.model_dump()
        )


@router.get("/privacy", summary="Get privacy compliance status")
async def get_privacy_compliance(request: Request) -> Dict[str, Any]:
    """
    Get privacy compliance status and violation reports.

    Returns:
        Privacy compliance health check results
    """
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat_history",
            message="Chat history feature is not enabled",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )

    try:
        privacy_health = chat_monitoring.check_privacy_compliance()
        return privacy_health.to_dict()

    except Exception as e:
        log.error(f"Privacy compliance check failed: {e}")
        error = create_internal_error(
            message=f"Privacy compliance check failed: {str(e)}",
            error_type="privacy_compliance_check_failed",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=500,
            detail=error.model_dump()
        )


@router.get("/metrics", summary="Get performance metrics")
async def get_performance_metrics(
    request: Request,
    hours: int = Query(24, ge=1, le=168, description="Time period in hours (max 7 days)")
) -> Dict[str, Any]:
    """
    Get performance metrics for the specified time period.

    Args:
        hours: Number of hours to include in metrics (1-168)

    Returns:
        Performance metrics summary
    """
    if not is_chat_history_enabled():
        error = create_service_unavailable_error(
            service="chat_history",
            message="Chat history feature is not enabled",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )

    try:
        metrics_summary = chat_monitoring.get_performance_summary(hours=hours)
        return metrics_summary

    except Exception as e:
        log.error(f"Performance metrics retrieval failed: {e}")
        error = create_internal_error(
            message=f"Performance metrics retrieval failed: {str(e)}",
            error_type="performance_metrics_retrieval_failed",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=500,
            detail=error.model_dump()
        )


@router.get("/monitoring", summary="Get monitoring service status")
async def get_monitoring_status(request: Request) -> Dict[str, Any]:
    """
    Get status of the monitoring service itself.

    Returns:
        Monitoring service status and statistics
    """
    try:
        return chat_monitoring.get_monitoring_status()

    except Exception as e:
        log.error(f"Monitoring status check failed: {e}")
        error = create_internal_error(
            message=f"Monitoring status check failed: {str(e)}",
            error_type="monitoring_status_check_failed",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=500,
            detail=error.model_dump()
        )


@router.post("/cleanup", summary="Trigger monitoring data cleanup")
async def trigger_cleanup(request: Request) -> Dict[str, Any]:
    """
    Manually trigger cleanup of old monitoring data.

    Returns:
        Cleanup operation result
    """
    try:
        chat_monitoring.cleanup_old_data()

        return {
            "status": "success",
            "message": "Monitoring data cleanup completed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        log.error(f"Monitoring cleanup failed: {e}")
        error = create_internal_error(
            message=f"Monitoring cleanup failed: {str(e)}",
            error_type="monitoring_cleanup_failed",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=500,
            detail=error.model_dump()
        )