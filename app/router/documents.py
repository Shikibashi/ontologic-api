"""
Documents Router - File upload and management endpoints.

Provides endpoints for uploading, listing, and deleting documents (PDF, Markdown, DOCX, TXT)
with username-based organization in Qdrant collections.

SECURITY: All endpoints require JWT authentication. Username is extracted from the
authenticated user token, preventing unauthorized access and cross-user data access.
"""

from typing import List, Dict, Any, Optional
import time
import math
from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from qdrant_client.http.exceptions import UnexpectedResponse, ResponseHandlingException, ApiException

from app.core.dependencies import QdrantManagerDep, require_documents_enabled, SubscriptionManagerDep
from app.core.rate_limiting import limiter, get_default_limit, get_upload_limit
from app.core.logger import log
from app.services.qdrant_upload import QdrantUploadService
from app.services.chat_monitoring import chat_monitoring, MetricType
from app.config.settings import get_settings
from app.core.auth_config import current_active_user
from app.core.user_models import User
from app.core.auth_helpers import get_username_from_user
from app.core.subscription_helpers import check_subscription_access, track_subscription_tokens
from app.core.constants import CHARS_PER_TOKEN_ESTIMATE
from app.core.error_responses import (
    create_validation_error,
    create_not_found_error,
    create_internal_error,
    create_authorization_error
)
from app.core.qdrant_helpers import check_collection_exists, CollectionCheckResult
from app.services.monitoring_helpers import safe_record_metric


router = APIRouter()


# Pydantic models for request/response
class DocumentUploadResponse(BaseModel):
    """Response model for document upload."""

    status: str
    file_id: str
    filename: str
    collection: str
    chunks_uploaded: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentMetadata(BaseModel):
    """Document metadata model."""

    title: Optional[str] = None
    author: Optional[str] = None
    topic: Optional[str] = None
    document_type: Optional[str] = None


class DocumentListItem(BaseModel):
    """Model for a single document in list response."""

    file_id: str
    filename: str
    document_type: str
    chunks: int
    uploaded_at: str
    metadata: DocumentMetadata


class DocumentListResponse(BaseModel):
    """Response model for document list endpoint."""

    documents: List[DocumentListItem]
    total: int
    limit: int
    offset: int


class DocumentDeleteResponse(BaseModel):
    """Response model for document deletion."""

    status: str
    file_id: str
    filename: str
    chunks_deleted: int


# Configuration
settings = get_settings()
MAX_UPLOAD_SIZE_MB = settings.max_upload_size_mb  # Pydantic guarantees this exists
ALLOWED_EXTENSIONS = {"pdf", "md", "docx", "txt"}

# Magic byte signatures for file type validation
FILE_SIGNATURES = {
    "pdf": [
        b"%PDF-",  # PDF files start with %PDF-
    ],
    "docx": [
        b"PK\x03\x04",  # DOCX is a ZIP archive (Office Open XML)
    ],
    "txt": None,  # Plain text has no magic bytes - validate as UTF-8
    "md": None,  # Markdown is plain text - validate as UTF-8
}


def validate_file_content_type(
    file_bytes: bytes,
    expected_extension: str,
    request_id: Optional[str] = None
) -> bool:
    """
    Validate file content using magic bytes (file signature).

    Args:
        file_bytes: Raw file bytes
        expected_extension: Expected file extension
        request_id: Optional request ID for error tracking

    Returns:
        True if file content matches expected type

    Raises:
        HTTPException: If file content doesn't match extension
    """
    # For text-based files (txt, md), validate UTF-8 encoding
    if expected_extension in {"txt", "md"}:
        try:
            file_bytes.decode("utf-8")
            return True
        except UnicodeDecodeError:
            error = create_validation_error(
                field="file",
                message=f"File appears to be corrupted or contains non-text data. Please ensure the file is a valid {expected_extension.upper()} text file encoded in UTF-8.",
                request_id=request_id
            )
            raise HTTPException(
                status_code=400,
                detail=error.model_dump()
            )

    # For binary files, check magic bytes
    signatures = FILE_SIGNATURES.get(expected_extension)
    if not signatures:
        # No signature check defined - allow by default
        return True

    # Check if file starts with any valid signature
    for signature in signatures:
        if file_bytes.startswith(signature):
            return True

    # No matching signature found - provide actionable guidance
    error = create_validation_error(
        field="file",
        message=f"File has .{expected_extension} extension but content does not match expected {expected_extension.upper()} format. The file may be corrupted, renamed incorrectly, or saved in an unsupported format. Please verify the file is a valid {expected_extension.upper()} file.",
        request_id=request_id
    )
    raise HTTPException(
        status_code=400,
        detail=error.model_dump()
    )


def validate_file_upload(
    file: UploadFile,
    username: str,
    request_id: Optional[str] = None
) -> None:
    """
    Validate file upload parameters.

    Args:
        file: Uploaded file
        username: Username for the upload (extracted from JWT, always valid)
        request_id: Optional request ID for error tracking

    Raises:
        HTTPException: If validation fails
    """
    # Username is now extracted from JWT token, so it's always valid
    # No need to validate username anymore

    if not file.filename:
        error = create_validation_error(
            field="filename",
            message="Filename is required",
            request_id=request_id
        )
        raise HTTPException(status_code=400, detail=error.model_dump())

    # Check file extension
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        error = create_validation_error(
            field="file",
            message=f"Unsupported file type: {file_ext}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}",
            request_id=request_id
        )
        raise HTTPException(
            status_code=400,
            detail=error.model_dump()
        )


@router.post("/upload", response_model=DocumentUploadResponse)
@limiter.limit(get_upload_limit)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    qdrant_manager: QdrantManagerDep = None,
    subscription_manager: SubscriptionManagerDep = None,
    _: None = Depends(require_documents_enabled),
) -> DocumentUploadResponse:
    """
    Upload a document (PDF, Markdown, DOCX, or TXT) to user's Qdrant collection.

    The document will be parsed, chunked semantically, embedded, and stored
    in a user-specific collection for later retrieval during chat.

    **SECURITY**: Requires JWT authentication. Username is automatically extracted
    from the authenticated user's token.

    Args:
        file: Document file to upload
        user: Authenticated user (automatically injected from JWT token)
        qdrant_manager: Injected Qdrant manager dependency
        subscription_manager: Subscription manager for access control

    Returns:
        Upload result with file_id and metadata

    Raises:
        HTTPException: If upload fails or validation errors occur
    """
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(user, subscription_manager, "/documents/upload", request)

    # Extract username from authenticated user
    username = get_username_from_user(user)

    # Start metrics tracking
    start_time = time.time()
    file_ext = file.filename.split(".")[-1].lower() if file.filename else "unknown"

    # Validate inputs
    validate_file_upload(file, username, request_id=getattr(request.state, 'request_id', None))

    try:
        # Read file content
        file_bytes = await file.read()

        # Check file size
        file_size_mb = len(file_bytes) / (1024 * 1024)

        # Record file size metric
        chat_monitoring.record_histogram(
            "document_upload_size_mb",
            file_size_mb,
            {"file_type": file_ext, "username": username},
        )

        if file_size_mb > MAX_UPLOAD_SIZE_MB:
            # Record 413 error metric
            safe_record_metric(
                "document_upload_errors",
                metric_type="counter",
                labels={"error_type": "413_file_too_large", "file_type": file_ext}
            )
            error = create_validation_error(
                field="file",
                message=f"File too large: {file_size_mb:.2f}MB (max {MAX_UPLOAD_SIZE_MB}MB)",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(
                status_code=413,
                detail=error.model_dump()
            )

        # Validate file content using magic bytes
        validate_file_content_type(file_bytes, file_ext, request_id=getattr(request.state, 'request_id', None))

        # Create upload service instance
        upload_service = QdrantUploadService(qdrant_client=qdrant_manager.qclient)

        # Upload file with username metadata
        result = await upload_service.upload_file(
            file_bytes=file_bytes,
            filename=file.filename,
            collection=username,  # User-specific collection
            metadata={"username": username},
        )

        # Check for errors in result
        if "error" in result:
            log.error(f"Upload failed for user {username}: {result['error']}")
            # Record upload failure metric - use safe_record_metric to prevent monitoring failures from breaking graceful degradation
            safe_record_metric(
                "document_upload_errors",
                metric_type="counter",
                labels={"error_type": "500_upload_failed", "file_type": file_ext}
            )
            error = create_internal_error(
                message=f"Failed to upload document: {result['error']}",
                error_type="upload_failed",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(
                status_code=500,
                detail=error.model_dump()
            )

        log.info(
            f"Successfully uploaded {file.filename} for user {username} ({result['chunks_uploaded']} chunks)"
        )

        # Record success metrics
        duration_ms = (time.time() - start_time) * 1000
        chat_monitoring.record_counter(
            "document_upload_success",
            {"file_type": file_ext, "username": username},
        )
        chat_monitoring.record_timer_ms(
            "document_upload_duration_ms",
            duration_ms,
            {"file_type": file_ext},
        )
        chat_monitoring.record_histogram(
            "document_chunks_created",
            result["chunks_uploaded"],
            {"file_type": file_ext},
        )

        # Track subscription usage for document upload
        # Use actual text content from upload result instead of raw file bytes
        char_count = result.get('char_count')
        if char_count is None:
            # Fallback: use sum of character counts from all chunks
            chunks = result.get('chunks', [])
            if chunks and hasattr(chunks[0], 'text'):
                char_count = sum(len(chunk.text) for chunk in chunks)
                log.info(
                    f"char_count missing from upload result for user={username}, "
                    f"file={file.filename}; calculated {char_count} chars from {len(chunks)} chunks"
                )
            else:
                # Final fallback: use file size as proxy
                file_size_bytes = len(file_bytes)
                char_count = max(file_size_bytes, 100)
                log.warning(
                    f"upload_service missing char_count and chunks for user={username}, "
                    f"file={file.filename}; using file_size={file_size_bytes} as estimate"
                )
        estimated_tokens = max(1, math.ceil(char_count / CHARS_PER_TOKEN_ESTIMATE))
        await track_subscription_tokens(
            user, subscription_manager,
            "/documents/upload",
            estimated_tokens
        )

        # Return response
        return DocumentUploadResponse(
            status=result["status"],
            file_id=result["file_id"],
            filename=result["filename"],
            collection=result["collection"],
            chunks_uploaded=result["chunks_uploaded"],
            metadata={},
        )

    except HTTPException as http_exc:
        # Record HTTP error metrics if not already recorded - use safe_record_metric in error paths
        if http_exc.status_code == 400:
            safe_record_metric(
                "document_upload_errors",
                metric_type="counter",
                labels={"error_type": "400_validation_error", "file_type": file_ext}
            )
        raise
    except (ConnectionError, TimeoutError) as e:
        log.error(
            f"Connection error during document upload for user {username}: {e}",
            exc_info=True,
        )
        safe_record_metric(
            "document_upload_errors",
            metric_type="counter",
            labels={"error_type": "503_connection_error", "file_type": file_ext}
        )
        error = create_internal_error(
            message="Failed to connect to document service. Please try again.",
            error_type="connection_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )
    except (UnexpectedResponse, ResponseHandlingException, ApiException) as e:
        log.error(
            f"Qdrant error during document upload for user {username}: {e}",
            exc_info=True,
        )
        safe_record_metric(
            "document_upload_errors",
            metric_type="counter",
            labels={"error_type": "503_qdrant_error", "file_type": file_ext}
        )
        error = create_internal_error(
            message="Document storage service error. Please try again.",
            error_type="qdrant_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )


@router.get("/list", response_model=DocumentListResponse)
@limiter.limit(get_default_limit)
async def list_documents(
    request: Request,
    user: User = Depends(current_active_user),
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of documents to return"
    ),
    offset: int = Query(0, ge=0, description="Number of documents to skip"),
    qdrant_manager: QdrantManagerDep = None,
    subscription_manager: SubscriptionManagerDep = None,
    _: None = Depends(require_documents_enabled),
) -> DocumentListResponse:
    """
    List all documents uploaded by the authenticated user.

    **SECURITY**: Requires JWT authentication. Only returns documents uploaded by
    the authenticated user.

    Args:
        user: Authenticated user (automatically injected from JWT token)
        limit: Maximum number of documents to return
        offset: Number of documents to skip for pagination
        qdrant_manager: Injected Qdrant manager dependency
        subscription_manager: Subscription manager for access control

    Returns:
        List of documents with metadata

    Raises:
        HTTPException: If listing fails
    """
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(user, subscription_manager, "/documents/list", request)

    # Extract username from authenticated user
    username = get_username_from_user(user)

    try:
        # Check if collection exists using centralized helper
        result = await check_collection_exists(
            qdrant_manager.qclient,
            username,
            f"[list_documents user={username}] "
        )

        if result == CollectionCheckResult.CONNECTION_ERROR:
            error = create_internal_error(
                message="Failed to connect to document service",
                error_type="connection_error",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=503, detail=error.model_dump())
        elif result == CollectionCheckResult.NOT_FOUND:
            # User has no documents yet (expected for new users)
            return DocumentListResponse(
                documents=[], total=0, limit=limit, offset=offset
            )

        # Scroll through collection to find unique documents
        # We'll group by file_id to get unique documents
        documents_dict: Dict[str, DocumentListItem] = {}
        scroll_offset = None

        while True:
            scroll_result = await qdrant_manager.qclient.scroll(
                collection_name=username,
                limit=100,  # Process in batches
                offset=scroll_offset,
                with_payload=True,
                with_vectors=False,
            )

            points, scroll_offset = scroll_result

            if not points:
                break

            # Group by file_id
            for point in points:
                if not hasattr(point, "payload") or not point.payload:
                    continue

                file_id = point.payload.get("file_id")
                if not file_id or file_id in documents_dict:
                    # Skip if no file_id or already seen
                    if file_id and file_id in documents_dict:
                        documents_dict[file_id].chunks += 1
                    continue

                # First time seeing this file_id
                filename = point.payload.get("filename", "Unknown")
                document_type = point.payload.get("document_type", "unknown")
                uploaded_at = point.payload.get("uploaded_at", "Unknown")

                # Extract metadata
                metadata = DocumentMetadata(
                    title=point.payload.get("title"),
                    author=point.payload.get("author"),
                    topic=point.payload.get("topic"),
                    document_type=document_type,
                )

                documents_dict[file_id] = DocumentListItem(
                    file_id=file_id,
                    filename=filename,
                    document_type=document_type,
                    chunks=1,
                    uploaded_at=uploaded_at,
                    metadata=metadata,
                )

            # Stop if we've seen enough documents (past offset + limit)
            if len(documents_dict) >= offset + limit:
                break

            if scroll_offset is None:
                break

        # Convert to list and apply pagination
        all_documents = list(documents_dict.values())
        total = len(all_documents)
        paginated_documents = all_documents[offset : offset + limit]

        log.info(
            f"Listed {len(paginated_documents)} documents for user {username} (total: {total})"
        )

        return DocumentListResponse(
            documents=paginated_documents, total=total, limit=limit, offset=offset
        )

    except HTTPException:
        raise
    except (ConnectionError, TimeoutError) as e:
        log.error(f"Connection error listing documents for user {username}: {e}", exc_info=True)
        error = create_internal_error(
            message="Failed to connect to document service",
            error_type="connection_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )
    except (UnexpectedResponse, ResponseHandlingException, ApiException) as e:
        log.error(f"Qdrant error listing documents for user {username}: {e}", exc_info=True)
        error = create_internal_error(
            message="Document storage service error",
            error_type="qdrant_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )


@router.delete("/{file_id}", response_model=DocumentDeleteResponse)
@limiter.limit(get_default_limit)
async def delete_document(
    request: Request,
    file_id: str,
    user: User = Depends(current_active_user),
    qdrant_manager: QdrantManagerDep = None,
    subscription_manager: SubscriptionManagerDep = None,
    _: None = Depends(require_documents_enabled),
) -> DocumentDeleteResponse:
    """
    Delete a document and all its chunks from user's collection.

    **SECURITY**: Requires JWT authentication. Users can only delete their own documents.
    The document owner is verified against the authenticated user's username.

    Args:
        file_id: Unique identifier of the file to delete
        user: Authenticated user (automatically injected from JWT token)
        qdrant_manager: Injected Qdrant manager dependency
        subscription_manager: Subscription manager for access control

    Returns:
        Deletion confirmation with chunks deleted count

    Raises:
        HTTPException: If deletion fails or unauthorized
    """
    # Subscription check: Enforce access control if payments are enabled
    await check_subscription_access(user, subscription_manager, "/documents/delete", request)

    # Extract username from authenticated user
    username = get_username_from_user(user)

    try:
        # Check if collection exists using centralized helper
        result = await check_collection_exists(
            qdrant_manager.qclient,
            username,
            f"[delete_document user={username}] "
        )

        if result == CollectionCheckResult.CONNECTION_ERROR:
            error = create_internal_error(
                message="Failed to connect to document service",
                error_type="connection_error",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(status_code=503, detail=error.model_dump())
        elif result == CollectionCheckResult.NOT_FOUND:
            # No documents to delete
            error = create_not_found_error(
                resource="documents",
                identifier=username,
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(
                status_code=404,
                detail=error.model_dump()
            )

        # Delete all points with matching file_id
        # Use scroll to find all matching points first
        deleted_count = 0
        scroll_filter = {
            "must": [
                {"key": "file_id", "match": {"value": file_id}},
                {"key": "username", "match": {"value": username}},
            ]
        }

        # Scroll through matching points
        point_ids = []
        offset = None

        while True:
            scroll_result = await qdrant_manager.qclient.scroll(
                collection_name=username,
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )

            points, offset = scroll_result

            if not points:
                break

            point_ids.extend([str(point.id) for point in points])

            if offset is None:
                break

        if not point_ids:
            # No points found matching both file_id AND username - this is an authorization failure
            # to prevent resource enumeration attacks (don't reveal whether file exists for other users)
            error = create_authorization_error(
                message="Access denied to this document",
                request_id=getattr(request.state, 'request_id', None)
            )
            raise HTTPException(
                status_code=403,
                detail=error.model_dump()
            )

        # Delete all points
        await qdrant_manager.qclient.delete(
            collection_name=username, points_selector=point_ids
        )

        deleted_count = len(point_ids)

        log.info(
            f"Deleted document {file_id} for user {username} ({deleted_count} chunks)"
        )

        return DocumentDeleteResponse(
            status="success",
            file_id=file_id,
            filename="unknown",  # We don't have filename from point IDs alone
            chunks_deleted=deleted_count,
        )

    except HTTPException:
        raise
    except (ConnectionError, TimeoutError) as e:
        log.error(
            f"Connection error deleting document {file_id} for user {username}: {e}", exc_info=True
        )
        error = create_internal_error(
            message="Failed to connect to document service",
            error_type="connection_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )
    except (UnexpectedResponse, ResponseHandlingException, ApiException) as e:
        log.error(
            f"Qdrant error deleting document {file_id} for user {username}: {e}", exc_info=True
        )
        error = create_internal_error(
            message="Document storage service error",
            error_type="qdrant_error",
            request_id=getattr(request.state, 'request_id', None)
        )
        raise HTTPException(
            status_code=503,
            detail=error.model_dump()
        )
