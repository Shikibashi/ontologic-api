"""
Standardized error response formats for consistent API error handling.

All API endpoints should use these response models for errors to ensure:
- Consistent error structure across the API
- Machine-readable error codes
- Human-readable error messages
- Detailed context for debugging
- Request traceability
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed information about a specific error."""

    type: str = Field(
        ...,
        description="Error classification (e.g., 'validation_error', 'timeout', 'not_found')",
    )
    message: str = Field(..., description="Human-readable error message")
    field: Optional[str] = Field(
        None, description="Field name for validation errors"
    )
    context: Optional[Dict[str, Any]] = Field(
        None, description="Additional context about the error"
    )


class ErrorResponse(BaseModel):
    """Standard API error response format."""

    error: str = Field(..., description="Short error code (e.g., 'timeout', 'not_found')")
    message: str = Field(..., description="Human-readable summary of the error")
    details: Optional[List[ErrorDetail]] = Field(
        None, description="Detailed error information"
    )
    request_id: Optional[str] = Field(None, description="Request ID for tracking")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of when the error occurred",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error": "timeout",
                "message": "LLM response generation timed out",
                "details": [
                    {
                        "type": "llm_timeout",
                        "message": "Response took longer than 120 seconds",
                        "context": {"timeout_seconds": 120, "query_length": 500},
                    }
                ],
                "request_id": "req_abc123",
                "timestamp": "2025-10-01T12:34:56.789Z",
            }
        }


def create_error_response(
    error_code: str,
    message: str,
    details: Optional[List[ErrorDetail]] = None,
    request_id: Optional[str] = None,
) -> ErrorResponse:
    """
    Create a standardized error response.

    Args:
        error_code: Short error code (e.g., 'timeout', 'not_found')
        message: Human-readable error summary
        details: Optional list of detailed error information
        request_id: Optional request ID for tracking

    Returns:
        ErrorResponse object with consistent structure

    Example:
        >>> error = create_error_response(
        ...     error_code="timeout",
        ...     message="Request timed out",
        ...     details=[ErrorDetail(
        ...         type="llm_timeout",
        ...         message="LLM took too long",
        ...         context={"timeout": 120}
        ...     )]
        ... )
    """
    return ErrorResponse(
        error=error_code,
        message=message,
        details=details,
        request_id=request_id,
    )


def create_validation_error(
    field: str, message: str, request_id: Optional[str] = None
) -> ErrorResponse:
    """Create a validation error response."""
    return create_error_response(
        error_code="validation_error",
        message="Request validation failed",
        details=[
            ErrorDetail(
                type="validation_error",
                message=message,
                field=field,
            )
        ],
        request_id=request_id,
    )


def create_timeout_error(
    timeout_seconds: int,
    operation: str = "operation",
    request_id: Optional[str] = None,
) -> ErrorResponse:
    """Create a timeout error response."""
    return create_error_response(
        error_code="timeout",
        message=f"{operation.capitalize()} timed out after {timeout_seconds} seconds",
        details=[
            ErrorDetail(
                type="timeout",
                message=f"The {operation} took longer than the allowed {timeout_seconds} seconds",
                context={"timeout_seconds": timeout_seconds, "operation": operation},
            )
        ],
        request_id=request_id,
    )


def create_not_found_error(
    resource: str, identifier: Optional[str] = None, request_id: Optional[str] = None
) -> ErrorResponse:
    """Create a not found error response."""
    message = f"{resource} not found"
    if identifier:
        message = f"{resource} '{identifier}' not found"

    return create_error_response(
        error_code="not_found",
        message=message,
        details=[
            ErrorDetail(
                type="not_found",
                message=message,
                context={"resource": resource, "identifier": identifier},
            )
        ],
        request_id=request_id,
    )


def create_authentication_error(
    message: str = "Authentication required", request_id: Optional[str] = None
) -> ErrorResponse:
    """Create an authentication error response."""
    return create_error_response(
        error_code="authentication_required",
        message=message,
        details=[
            ErrorDetail(
                type="authentication_error",
                message=message,
            )
        ],
        request_id=request_id,
    )


def create_authorization_error(
    message: str = "Access denied", request_id: Optional[str] = None
) -> ErrorResponse:
    """Create an authorization error response."""
    return create_error_response(
        error_code="access_denied",
        message=message,
        details=[
            ErrorDetail(
                type="authorization_error",
                message=message,
            )
        ],
        request_id=request_id,
    )


def create_forbidden_error(
    message: str = "Forbidden", request_id: Optional[str] = None
) -> ErrorResponse:
    """Create a forbidden error response."""
    return create_error_response(
        error_code="forbidden",
        message=message,
        details=[
            ErrorDetail(
                type="forbidden_error",
                message=message,
            )
        ],
        request_id=request_id,
    )


def create_internal_error(
    message: str = "Internal server error",
    error_type: Optional[str] = None,
    request_id: Optional[str] = None,
) -> ErrorResponse:
    """Create an internal server error response."""
    return create_error_response(
        error_code="internal_error",
        message=message,
        details=[
            ErrorDetail(
                type=error_type or "internal_error",
                message=message,
            )
        ],
        request_id=request_id,
    )


def create_service_unavailable_error(
    service: str = "service",
    message: Optional[str] = None,
    request_id: Optional[str] = None,
) -> ErrorResponse:
    """Create a service unavailable error response."""
    error_message = message or f"{service.capitalize()} temporarily unavailable"
    return create_error_response(
        error_code="service_unavailable",
        message=error_message,
        details=[
            ErrorDetail(
                type="service_unavailable",
                message=error_message,
                context={"service": service},
            )
        ],
        request_id=request_id,
    )


def create_invalid_response_error(
    service: str = "service",
    message: Optional[str] = None,
    request_id: Optional[str] = None,
) -> ErrorResponse:
    """Create an invalid response error."""
    error_message = message or f"Invalid response from {service}"
    return create_error_response(
        error_code="invalid_response",
        message=error_message,
        details=[
            ErrorDetail(
                type="invalid_response",
                message=error_message,
                context={"service": service},
            )
        ],
        request_id=request_id,
    )


def create_conflict_error(
    message: str,
    conflicting_params: Optional[List[str]] = None,
    request_id: Optional[str] = None,
) -> ErrorResponse:
    """Create a conflict error response (e.g., mutually exclusive parameters)."""
    return create_error_response(
        error_code="conflict",
        message=message,
        details=[
            ErrorDetail(
                type="parameter_conflict",
                message=message,
                context={"conflicting_params": conflicting_params} if conflicting_params else None,
            )
        ],
        request_id=request_id,
    )
