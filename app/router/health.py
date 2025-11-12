"""
Health check endpoints for monitoring and Kubernetes probes.

Provides three endpoints:
- /health - Detailed status of all services
- /health/ready - Readiness probe (all services available)
- /health/live - Liveness probe (app is running)
"""

import asyncio
from typing import Dict, Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.dependencies import (
    get_cache_service,
    get_llm_manager,
    get_qdrant_manager,
)
from app.core.chat_dependencies import get_feature_flags, get_chat_config
from app.core.logger import log

router = APIRouter(prefix="/health", tags=["health"])


async def check_database_health() -> Dict[str, Any]:
    """
    Check database connectivity.
    
    Returns:
        Dictionary with status and details
    """
    try:
        from app.core.database import engine
        
        # Test database connection with a simple query
        async with engine.connect() as conn:
            # Execute a simple query to verify connection
            await conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        log.warning(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Database connection failed: {str(e)}"
        }


async def check_qdrant_health(request: Request) -> Dict[str, Any]:
    """
    Check Qdrant vector database connectivity.
    
    Returns:
        Dictionary with status and details
    """
    try:
        qdrant = get_qdrant_manager(request)
        # Use existing validate_connection method with timeout
        await asyncio.wait_for(
            qdrant.validate_connection(),
            timeout=5.0
        )
        
        # Get collection count for additional info
        collections = await qdrant.get_collections()
        collection_count = len(collections.collections)
        
        return {
            "status": "healthy",
            "message": "Qdrant connection successful",
            "collections": collection_count
        }
    except asyncio.TimeoutError:
        log.warning("Qdrant health check timed out")
        return {
            "status": "unhealthy",
            "message": "Qdrant connection timed out"
        }
    except Exception as e:
        log.warning(f"Qdrant health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Qdrant connection failed: {str(e)}"
        }


async def check_redis_health(request: Request) -> Dict[str, Any]:
    """
    Check Redis cache connectivity.
    
    Returns:
        Dictionary with status and details
    """
    try:
        cache_service = get_cache_service(request)
        
        # Check if Redis is enabled in config
        if not cache_service._config.get('enabled', True):
            return {
                "status": "disabled",
                "message": "Redis caching is disabled in configuration"
            }
        
        # Test Redis connection
        is_healthy = await asyncio.wait_for(
            cache_service.health_check(),
            timeout=3.0
        )
        
        if is_healthy:
            # Get cache statistics
            stats = cache_service.get_cache_stats()
            return {
                "status": "healthy",
                "message": "Redis connection successful",
                "stats": {
                    "hit_rate": stats.get('hit_rate', 0),
                    "hits": stats.get('hits', 0),
                    "misses": stats.get('misses', 0)
                }
            }
        else:
            return {
                "status": "unhealthy",
                "message": "Redis connection failed"
            }
    except asyncio.TimeoutError:
        log.warning("Redis health check timed out")
        return {
            "status": "unhealthy",
            "message": "Redis connection timed out"
        }
    except Exception as e:
        log.warning(f"Redis health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Redis connection failed: {str(e)}"
        }


async def check_chat_history_health(request: Request) -> Dict[str, Any]:
    """
    Check chat history feature status and configuration.
    
    Returns:
        Dictionary with status and details
    """
    try:
        from app.config.settings import get_settings
        
        settings = get_settings()
        
        # Get feature flags and chat config safely
        try:
            # Simple check without complex dependencies
            chat_enabled = getattr(settings, 'chat_history', False)
            if not chat_enabled:
                return {
                    "status": "disabled",
                    "message": "Chat history feature is disabled",
                    "config": {"enabled": False}
                }
            
            # Basic configuration check
            env = getattr(settings, 'env', 'dev')
            collection_name = f"Chat_History_{env.title()}" if env != 'prod' else "Chat_History"
            
            return {
                "status": "healthy",
                "message": "Chat history feature is enabled",
                "config": {
                    "enabled": True,
                    "environment": env,
                    "collection_name": collection_name
                }
            }
            
        except Exception as config_error:
            log.warning(f"Chat config initialization failed: {config_error}")
            return {
                "status": "error",
                "message": f"Chat configuration error: {str(config_error)}"
            }

        
    except Exception as e:
        log.warning(f"Chat history health check failed: {e}")
        return {
            "status": "error",
            "message": f"Chat history health check failed: {str(e)}"
        }


async def check_llm_health(request: Request) -> Dict[str, Any]:
    """
    Check LLM service availability by testing vector generation capability.
    
    Performs actual vector generation test to ensure chat history upload functionality
    is working properly, which is critical for chat vector operations.
    
    Returns:
        Dictionary with status and details
    """
    try:
        # Validate LLM manager can be instantiated
        llm = get_llm_manager(request)
        
        # Check if LLM client exists and is configured
        if not hasattr(llm, '_llm') or llm._llm is None:
            return {
                "status": "unhealthy",
                "message": "LLM client not initialized"
            }
        
        # Test actual vector generation capability (critical for chat history)
        try:
            test_text = "health check test message"
            vector = await asyncio.wait_for(
                llm.generate_dense_vector(test_text),
                timeout=10.0  # 10 second timeout for health check
            )
            
            # Validate vector dimensions (accept common embedding sizes)
            expected_dims = [384, 512, 768, 1024, 1536, 4096]  # Common embedding dimensions
            if not vector or len(vector) not in expected_dims:
                return {
                    "status": "unhealthy",
                    "message": f"Invalid vector generation: got {len(vector) if vector else 0} dimensions, expected one of {expected_dims}"
                }
            
            # Test vector quality (ensure not all zeros)
            vector_sum = sum(abs(v) for v in vector)
            if vector_sum < 0.1:  # Very low threshold to catch zero vectors
                return {
                    "status": "degraded",
                    "message": "Vector generation produces near-zero vectors"
                }
            
            # Check if SPLADE tokenizer is available (for PRF functionality)
            splade_available = hasattr(llm, 'splade_tokenizer') and llm.splade_tokenizer is not None
            
            # Basic configuration validation
            context_window = getattr(llm._llm, 'context_window', None)
            
            return {
                "status": "healthy",
                "message": "LLM service fully operational with vector generation",
                "capabilities": {
                    "vector_generation": True,
                    "vector_dimensions": len(vector),
                    "splade_available": splade_available,
                    "context_window": context_window
                },
                "test_results": {
                    "vector_magnitude": round(vector_sum, 4),
                    "test_text_length": len(test_text)
                }
            }
            
        except asyncio.TimeoutError:
            log.warning("LLM vector generation timed out")
            return {
                "status": "degraded",
                "message": "LLM vector generation is slow (>10s timeout)"
            }
        except Exception as vector_error:
            log.warning(f"LLM vector generation failed: {vector_error}")
            return {
                "status": "unhealthy",
                "message": f"Vector generation failed: {str(vector_error)}"
            }
        
    except ImportError as e:
        log.warning(f"LLM dependencies not available: {e}")
        return {
            "status": "unhealthy",
            "message": f"LLM dependencies missing: {str(e)}"
        }
    except Exception as e:
        log.warning(f"LLM health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"LLM service unavailable: {str(e)}"
        }


@router.get("", summary="Comprehensive health check")
async def health_check(request: Request, response: Response) -> Dict[str, Any]:
    """
    Comprehensive health check with detailed status of all services.
    
    Returns detailed information about:
    - Application status and version
    - Database connectivity
    - Qdrant vector database
    - Redis cache
    - LLM service
    
    Returns 200 if all critical services are healthy, 503 if any are unhealthy.
    """
    # Check all services in parallel for faster response
    db_health, qdrant_health, redis_health, llm_health, chat_health = await asyncio.gather(
        check_database_health(),
        check_qdrant_health(request),
        check_redis_health(request),
        check_llm_health(request),
        check_chat_history_health(request),
        return_exceptions=True
    )
    
    # Handle exceptions from gather
    if isinstance(db_health, Exception):
        db_health = {"status": "error", "message": str(db_health)}
    if isinstance(qdrant_health, Exception):
        qdrant_health = {"status": "error", "message": str(qdrant_health)}
    if isinstance(redis_health, Exception):
        redis_health = {"status": "error", "message": str(redis_health)}
    if isinstance(llm_health, Exception):
        llm_health = {"status": "error", "message": str(llm_health)}
    if isinstance(chat_health, Exception):
        chat_health = {"status": "error", "message": str(chat_health)}
    
    # Determine overall status
    # Critical services: database, qdrant, llm
    # Non-critical: redis (can run without cache)
    critical_services_healthy = (
        db_health.get("status") == "healthy" and
        qdrant_health.get("status") == "healthy" and
        llm_health.get("status") == "healthy"
    )
    
    overall_status = "healthy" if critical_services_healthy else "unhealthy"
    
    # Set HTTP status code
    if overall_status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        response.status_code = status.HTTP_200_OK
    
    return {
        "status": overall_status,
        "version": "1.0.0",
        "services": {
            "database": db_health,
            "qdrant": qdrant_health,
            "redis": redis_health,
            "llm": llm_health,
            "chat_history": chat_health
        }
    }


@router.get("/ready", summary="Readiness probe")
async def readiness_check(request: Request, response: Response) -> Dict[str, str]:
    """
    Kubernetes readiness probe.
    
    Checks if the application is ready to serve traffic by verifying
    that all critical services (database, Qdrant, LLM) are available.
    
    Returns 200 if ready, 503 if not ready.
    """
    try:
        # Check critical services only (faster than full health check)
        db_health, qdrant_health, llm_health = await asyncio.gather(
            check_database_health(),
            check_qdrant_health(request),
            check_llm_health(request),
            return_exceptions=True
        )
        
        # Handle exceptions
        if isinstance(db_health, Exception):
            db_health = {"status": "error"}
        if isinstance(qdrant_health, Exception):
            qdrant_health = {"status": "error"}
        if isinstance(llm_health, Exception):
            llm_health = {"status": "error"}
        
        # Check if all critical services are healthy
        is_ready = (
            db_health.get("status") == "healthy" and
            qdrant_health.get("status") == "healthy" and
            llm_health.get("status") == "healthy"
        )
        
        if is_ready:
            response.status_code = status.HTTP_200_OK
            return {"status": "ready"}
        else:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not ready"}
    
    except Exception as e:
        log.error(f"Readiness check failed: {e}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not ready", "error": str(e)}


@router.get("/live", summary="Liveness probe")
async def liveness_check() -> Dict[str, str]:
    """
    Kubernetes liveness probe.
    
    Simple check that the application is running and responsive.
    This endpoint should always return 200 unless the app is completely dead.
    
    Returns 200 if alive.
    """
    return {"status": "alive"}
