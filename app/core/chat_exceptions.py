"""
Chat-specific exceptions and error handling utilities.

This module provides specialized exceptions for chat operations with
graceful degradation support and detailed error context.
"""

from typing import Optional, Dict, Any, List
from enum import Enum
from app.core.exceptions import OntologicError, DatabaseError, LLMError


class ChatErrorSeverity(Enum):
    """Severity levels for chat errors."""
    LOW = "low"           # Non-critical, operation can continue
    MEDIUM = "medium"     # Important but recoverable
    HIGH = "high"         # Critical, operation should fail
    CRITICAL = "critical" # System-level failure


class ChatErrorCategory(Enum):
    """Categories of chat errors for better handling."""
    DATABASE = "database"
    VECTOR_STORE = "vector_store"
    VALIDATION = "validation"
    PRIVACY = "privacy"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    TIMEOUT = "timeout"
    RESOURCE = "resource"


class ChatError(OntologicError):
    """Base exception for chat-related errors with enhanced context."""
    
    def __init__(
        self,
        message: str,
        category: ChatErrorCategory,
        severity: ChatErrorSeverity = ChatErrorSeverity.MEDIUM,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
        fallback_available: bool = False,
        retry_after: Optional[int] = None
    ):
        self.category = category
        self.severity = severity
        self.recoverable = recoverable
        self.fallback_available = fallback_available
        self.retry_after = retry_after
        super().__init__(message, details)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "recoverable": self.recoverable,
            "fallback_available": self.fallback_available,
            "retry_after": self.retry_after,
            "details": self.details
        }


class ChatDatabaseError(ChatError, DatabaseError):
    """PostgreSQL database errors in chat operations."""
    
    def __init__(
        self,
        message: str,
        operation: str,
        session_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True
    ):
        self.operation = operation
        self.session_id = session_id
        
        enhanced_details = {
            "operation": operation,
            "session_id": session_id,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.DATABASE,
            severity=ChatErrorSeverity.HIGH,
            details=enhanced_details,
            recoverable=recoverable,
            fallback_available=False  # Database failures usually don't have fallbacks
        )


class ChatVectorStoreError(ChatError, LLMError):
    """Qdrant vector store errors in chat operations."""
    
    def __init__(
        self,
        message: str,
        operation: str,
        collection_name: Optional[str] = None,
        session_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = True,
        fallback_available: bool = True
    ):
        self.operation = operation
        self.collection_name = collection_name
        self.session_id = session_id
        
        enhanced_details = {
            "operation": operation,
            "collection_name": collection_name,
            "session_id": session_id,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.VECTOR_STORE,
            severity=ChatErrorSeverity.MEDIUM,
            details=enhanced_details,
            recoverable=recoverable,
            fallback_available=fallback_available,
            retry_after=30
        )


class ChatPrivacyError(ChatError):
    """Privacy and security violations in chat operations."""
    
    def __init__(
        self,
        message: str,
        violation_type: str,
        session_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.violation_type = violation_type
        self.session_id = session_id
        
        enhanced_details = {
            "violation_type": violation_type,
            "session_id": session_id,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.PRIVACY,
            severity=ChatErrorSeverity.CRITICAL,
            details=enhanced_details,
            recoverable=False,
            fallback_available=False
        )


class ChatValidationError(ChatError):
    """Input validation errors in chat operations."""
    
    def __init__(
        self,
        message: str,
        field: str,
        value: Any = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.field = field
        self.value = value
        
        enhanced_details = {
            "field": field,
            "value": str(value) if value is not None else None,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.VALIDATION,
            severity=ChatErrorSeverity.LOW,
            details=enhanced_details,
            recoverable=True,
            fallback_available=False
        )


class ChatConfigurationError(ChatError):
    """Configuration and feature flag errors."""
    
    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.config_key = config_key
        
        enhanced_details = {
            "config_key": config_key,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.CONFIGURATION,
            severity=ChatErrorSeverity.HIGH,
            details=enhanced_details,
            recoverable=False,
            fallback_available=False
        )


class ChatTimeoutError(ChatError):
    """Timeout errors in chat operations."""
    
    def __init__(
        self,
        message: str,
        operation: str,
        timeout_seconds: int,
        details: Optional[Dict[str, Any]] = None
    ):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        
        enhanced_details = {
            "operation": operation,
            "timeout_seconds": timeout_seconds,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.TIMEOUT,
            severity=ChatErrorSeverity.MEDIUM,
            details=enhanced_details,
            recoverable=True,
            fallback_available=True,
            retry_after=min(timeout_seconds * 2, 60)  # Exponential backoff, max 60s
        )


class ChatResourceError(ChatError):
    """Resource exhaustion errors (memory, connections, etc.)."""
    
    def __init__(
        self,
        message: str,
        resource_type: str,
        current_usage: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.resource_type = resource_type
        self.current_usage = current_usage
        
        enhanced_details = {
            "resource_type": resource_type,
            "current_usage": current_usage,
            **(details or {})
        }
        
        super().__init__(
            message=message,
            category=ChatErrorCategory.RESOURCE,
            severity=ChatErrorSeverity.HIGH,
            details=enhanced_details,
            recoverable=True,
            fallback_available=True,
            retry_after=60
        )


class ChatOperationResult:
    """Result wrapper for chat operations with error context."""
    
    def __init__(
        self,
        success: bool,
        data: Any = None,
        error: Optional[ChatError] = None,
        warnings: Optional[List[str]] = None,
        fallback_used: bool = False
    ):
        self.success = success
        self.data = data
        self.error = error
        self.warnings = warnings or []
        self.fallback_used = fallback_used
    
    @classmethod
    def success_result(cls, data: Any = None, warnings: Optional[List[str]] = None) -> 'ChatOperationResult':
        """Create a successful result."""
        return cls(success=True, data=data, warnings=warnings)
    
    @classmethod
    def error_result(cls, error: ChatError, fallback_data: Any = None) -> 'ChatOperationResult':
        """Create an error result with optional fallback data."""
        return cls(
            success=False,
            data=fallback_data,
            error=error,
            fallback_used=fallback_data is not None
        )
    
    @classmethod
    def fallback_result(cls, data: Any, original_error: ChatError, warnings: Optional[List[str]] = None) -> 'ChatOperationResult':
        """Create a result that used fallback due to error."""
        all_warnings = warnings or []
        all_warnings.append(f"Fallback used due to {original_error.category.value} error: {original_error.message}")
        
        return cls(
            success=True,
            data=data,
            error=original_error,
            warnings=all_warnings,
            fallback_used=True
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for API responses."""
        result = {
            "success": self.success,
            "data": self.data,
            "fallback_used": self.fallback_used
        }
        
        if self.warnings:
            result["warnings"] = self.warnings
        
        if self.error:
            result["error"] = self.error.to_dict()
        
        return result


def handle_chat_error(
    error: Exception,
    operation: str,
    session_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None
) -> ChatError:
    """
    Convert generic exceptions to appropriate ChatError instances.
    
    Args:
        error: The original exception
        operation: Description of the operation that failed
        session_id: Optional session ID for context
        context: Additional context information
        
    Returns:
        Appropriate ChatError instance
    """
    context = context or {}
    
    # Database-related errors
    if "database" in str(error).lower() or "postgresql" in str(error).lower():
        return ChatDatabaseError(
            message=f"Database operation failed: {str(error)}",
            operation=operation,
            session_id=session_id,
            details=context
        )
    
    # Qdrant/vector store errors
    if "qdrant" in str(error).lower() or "vector" in str(error).lower():
        return ChatVectorStoreError(
            message=f"Vector store operation failed: {str(error)}",
            operation=operation,
            session_id=session_id,
            details=context
        )
    
    # Timeout errors
    if "timeout" in str(error).lower() or isinstance(error, TimeoutError):
        return ChatTimeoutError(
            message=f"Operation timed out: {str(error)}",
            operation=operation,
            timeout_seconds=context.get("timeout_seconds", 30),
            details=context
        )
    
    # Validation errors
    if "validation" in str(error).lower() or "invalid" in str(error).lower():
        return ChatValidationError(
            message=f"Validation failed: {str(error)}",
            field=context.get("field", "unknown"),
            value=context.get("value"),
            details=context
        )
    
    # Privacy/security errors
    if "privacy" in str(error).lower() or "security" in str(error).lower() or "unauthorized" in str(error).lower():
        return ChatPrivacyError(
            message=f"Privacy violation: {str(error)}",
            violation_type=context.get("violation_type", "unknown"),
            session_id=session_id,
            details=context
        )
    
    # Default to generic chat error
    return ChatError(
        message=f"Chat operation failed: {str(error)}",
        category=ChatErrorCategory.NETWORK,  # Default category
        severity=ChatErrorSeverity.MEDIUM,
        details={
            "operation": operation,
            "session_id": session_id,
            "original_error": str(error),
            "error_type": type(error).__name__,
            **context
        }
    )