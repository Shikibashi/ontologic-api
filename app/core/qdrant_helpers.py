"""
Qdrant Helper Functions

Centralized utilities for common Qdrant operations with standardized exception handling.
Provides single source of truth for collection checks and other Qdrant patterns.
"""

from enum import Enum
from typing import Optional
from qdrant_client import AsyncQdrantClient
from app.core.logger import log


class CollectionCheckResult(Enum):
    """Result of checking if a Qdrant collection exists."""

    EXISTS = "exists"
    NOT_FOUND = "not_found"
    CONNECTION_ERROR = "connection_error"


async def check_collection_exists(
    qclient: AsyncQdrantClient,
    collection_name: str,
    log_prefix: str = ""
) -> CollectionCheckResult:
    """
    Check if a Qdrant collection exists with standardized exception handling.

    This helper provides consistent behavior for collection existence checks
    across the codebase, distinguishing between:
    - Collection exists (normal case)
    - Collection doesn't exist (expected for new users)
    - Infrastructure/connectivity failures (requires error handling)

    Args:
        qclient: Qdrant async client instance
        collection_name: Name of collection to check
        log_prefix: Optional prefix for log messages (e.g., "[endpoint user=alice] ")

    Returns:
        CollectionCheckResult enum:
        - EXISTS: Collection found and accessible
        - NOT_FOUND: Collection doesn't exist (user has no documents)
        - CONNECTION_ERROR: Qdrant connectivity failure

    Example:
        ```python
        from app.core.qdrant_helpers import check_collection_exists, CollectionCheckResult

        result = await check_collection_exists(qclient, username, f"[upload user={username}] ")

        if result == CollectionCheckResult.CONNECTION_ERROR:
            raise HTTPException(status_code=503, detail="Service unavailable")
        elif result == CollectionCheckResult.NOT_FOUND:
            return {"documents": []}  # No documents yet
        # else: EXISTS - proceed with operation
        ```
    """
    try:
        await qclient.get_collection(collection_name=collection_name)
        return CollectionCheckResult.EXISTS

    except (ConnectionError, TimeoutError) as e:
        # Infrastructure failure - Qdrant unavailable or network issue
        log.error(
            f"{log_prefix}Qdrant connection error checking collection '{collection_name}': {e}",
            exc_info=True,
            extra={"collection": collection_name, "error_type": type(e).__name__}
        )
        return CollectionCheckResult.CONNECTION_ERROR

    except Exception as e:
        # Collection doesn't exist (Qdrant raises generic Exception for 404)
        # This is expected for new users who haven't uploaded documents yet
        log.debug(
            f"{log_prefix}Collection '{collection_name}' not found: {e}",
            extra={"collection": collection_name, "error_type": type(e).__name__}
        )
        return CollectionCheckResult.NOT_FOUND
