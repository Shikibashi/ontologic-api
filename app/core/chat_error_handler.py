"""
Enhanced error handling and graceful degradation for chat operations.

This module provides comprehensive error handling with fallback mechanisms,
monitoring integration, and user-friendly error responses.
"""

import asyncio
from functools import wraps
from typing import Callable, Any, Optional, Dict, List, Union
from fastapi import HTTPException
from datetime import datetime, timezone

from app.core.logger import log
from app.core.chat_exceptions import (
    ChatError, ChatErrorSeverity, ChatErrorCategory,
    ChatDatabaseError, ChatVectorStoreError, ChatPrivacyError,
    ChatValidationError, ChatConfigurationError, ChatTimeoutError,
    ChatResourceError, ChatOperationResult, handle_chat_error
)
from app.core.exceptions import (
    LLMError, LLMTimeoutError, LLMUnavailableError, LLMResponseError,
    DatabaseError, ValidationError
)


class ChatErrorHandler:
    """
    Centralized error handling for chat operations with graceful degradation.
    
    Features:
    - Automatic error categorization and severity assessment
    - Graceful degradation with fallback mechanisms
    - Detailed logging and monitoring integration
    - User-friendly error responses
    - Retry logic with exponential backoff
    """
    
    def __init__(self):
        self.error_counts = {}  # Track error frequencies for monitoring
        self.fallback_usage = {}  # Track fallback mechanism usage
    
    def record_error(self, error: ChatError, operation: str) -> None:
        """Record error for monitoring and analytics."""
        error_key = f"{operation}:{error.category.value}:{error.severity.value}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        # Log based on severity
        if error.severity == ChatErrorSeverity.CRITICAL:
            log.critical(f"Critical chat error in {operation}: {error.message}", extra={
                "category": error.category.value,
                "severity": error.severity.value,
                "details": error.details,
                "recoverable": error.recoverable
            })
        elif error.severity == ChatErrorSeverity.HIGH:
            log.error(f"High severity chat error in {operation}: {error.message}", extra={
                "category": error.category.value,
                "details": error.details
            })
        elif error.severity == ChatErrorSeverity.MEDIUM:
            log.warning(f"Medium severity chat error in {operation}: {error.message}", extra={
                "category": error.category.value,
                "details": error.details
            })
        else:
            log.info(f"Low severity chat error in {operation}: {error.message}", extra={
                "category": error.category.value,
                "details": error.details
            })
    
    def record_fallback_usage(self, operation: str, fallback_type: str) -> None:
        """Record fallback mechanism usage for monitoring."""
        fallback_key = f"{operation}:{fallback_type}"
        self.fallback_usage[fallback_key] = self.fallback_usage.get(fallback_key, 0) + 1
        
        log.info(f"Fallback mechanism used in {operation}: {fallback_type}")
    
    async def execute_with_fallback(
        self,
        primary_operation: Callable,
        fallback_operation: Optional[Callable] = None,
        operation_name: str = "chat_operation",
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> ChatOperationResult:
        """
        Execute operation with automatic error handling and fallback.
        
        Args:
            primary_operation: Main operation to execute
            fallback_operation: Optional fallback operation if primary fails
            operation_name: Name of the operation for logging
            session_id: Optional session ID for context
            context: Additional context for error handling
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries (exponential backoff)
            
        Returns:
            ChatOperationResult with success/error information
        """
        context = context or {}
        last_error = None
        
        # Try primary operation with retries
        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(primary_operation):
                    result = await primary_operation()
                else:
                    result = primary_operation()
                
                # Success - return result
                warnings = []
                if attempt > 0:
                    warnings.append(f"Operation succeeded after {attempt} retries")
                
                return ChatOperationResult.success_result(data=result, warnings=warnings)
                
            except Exception as e:
                # Convert to ChatError
                chat_error = self._convert_to_chat_error(e, operation_name, session_id, context)
                last_error = chat_error
                
                # Record the error
                self.record_error(chat_error, operation_name)
                
                # Check if we should retry
                if attempt < max_retries and chat_error.recoverable:
                    delay = retry_delay * (2 ** attempt)  # Exponential backoff
                    log.warning(f"Retrying {operation_name} after {delay}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
                else:
                    break
        
        # Primary operation failed - try fallback if available
        if fallback_operation and last_error.fallback_available:
            try:
                log.info(f"Attempting fallback for {operation_name}")
                
                if asyncio.iscoroutinefunction(fallback_operation):
                    fallback_result = await fallback_operation()
                else:
                    fallback_result = fallback_operation()
                
                # Record fallback usage
                self.record_fallback_usage(operation_name, "primary_fallback")
                
                return ChatOperationResult.fallback_result(
                    data=fallback_result,
                    original_error=last_error,
                    warnings=[f"Primary operation failed, using fallback mechanism"]
                )
                
            except Exception as fallback_error:
                # Fallback also failed
                fallback_chat_error = self._convert_to_chat_error(
                    fallback_error, f"{operation_name}_fallback", session_id, context
                )
                self.record_error(fallback_chat_error, f"{operation_name}_fallback")
                
                log.error(f"Both primary and fallback operations failed for {operation_name}")
                
                # Return the more severe error
                final_error = last_error if last_error.severity.value >= fallback_chat_error.severity.value else fallback_chat_error
                return ChatOperationResult.error_result(final_error)
        
        # No fallback available or fallback not applicable
        return ChatOperationResult.error_result(last_error)
    
    def _convert_to_chat_error(
        self,
        error: Exception,
        operation: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ChatError:
        """Convert generic exception to ChatError."""
        if isinstance(error, ChatError):
            return error
        
        return handle_chat_error(error, operation, session_id, context)
    
    def create_http_response(self, result: ChatOperationResult) -> Union[Any, HTTPException]:
        """
        Convert ChatOperationResult to appropriate HTTP response.
        
        Args:
            result: The operation result to convert
            
        Returns:
            Either the successful data or raises HTTPException
        """
        if result.success:
            return result.data
        
        error = result.error
        
        # Map error categories to HTTP status codes
        status_code_map = {
            ChatErrorCategory.VALIDATION: 400,
            ChatErrorCategory.PRIVACY: 403,
            ChatErrorCategory.CONFIGURATION: 503,
            ChatErrorCategory.DATABASE: 500,
            ChatErrorCategory.VECTOR_STORE: 503,
            ChatErrorCategory.TIMEOUT: 504,
            ChatErrorCategory.RESOURCE: 503,
            ChatErrorCategory.NETWORK: 502
        }
        
        status_code = status_code_map.get(error.category, 500)
        
        # Create detailed error response
        detail = {
            "error": error.__class__.__name__,
            "message": error.message,
            "category": error.category.value,
            "recoverable": error.recoverable
        }
        
        # Add retry information if applicable
        if error.retry_after:
            detail["retry_after"] = error.retry_after
        
        # Add fallback information
        if error.fallback_available:
            detail["fallback_available"] = True
        
        # Include warnings if any
        if result.warnings:
            detail["warnings"] = result.warnings
        
        # Add details for debugging (but sanitize sensitive info)
        if error.details:
            sanitized_details = self._sanitize_error_details(error.details)
            detail["details"] = sanitized_details
        
        raise HTTPException(status_code=status_code, detail=detail)
    
    def _sanitize_error_details(self, details: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive information from error details."""
        sanitized = {}
        
        # List of keys that might contain sensitive information
        sensitive_keys = {"password", "token", "key", "secret", "api_key", "auth"}
        
        for key, value in details.items():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_error_details(value)
            else:
                sanitized[key] = value
        
        return sanitized
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics for monitoring."""
        return {
            "error_counts": dict(self.error_counts),
            "fallback_usage": dict(self.fallback_usage),
            "total_errors": sum(self.error_counts.values()),
            "total_fallbacks": sum(self.fallback_usage.values()),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def reset_statistics(self) -> None:
        """Reset error statistics (useful for testing or periodic resets)."""
        self.error_counts.clear()
        self.fallback_usage.clear()


# Global error handler instance
chat_error_handler = ChatErrorHandler()


def chat_error_guard(
    operation_name: Optional[str] = None,
    fallback_operation: Optional[Callable] = None,
    max_retries: int = 3,
    enable_fallback: bool = True
):
    """
    Decorator for chat operations with comprehensive error handling.
    
    Args:
        operation_name: Name of the operation for logging
        fallback_operation: Optional fallback function
        max_retries: Maximum retry attempts
        enable_fallback: Whether to enable fallback mechanisms
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            op_name = operation_name or func.__name__
            
            # Extract session_id from kwargs if available
            session_id = kwargs.get('session_id')
            
            # Create primary operation wrapper
            async def primary_op():
                return await func(*args, **kwargs)
            
            # Execute with error handling
            result = await chat_error_handler.execute_with_fallback(
                primary_operation=primary_op,
                fallback_operation=fallback_operation if enable_fallback else None,
                operation_name=op_name,
                session_id=session_id,
                max_retries=max_retries
            )
            
            # Convert to HTTP response
            return chat_error_handler.create_http_response(result)
        
        return wrapper
    return decorator


def database_fallback_decorator(fallback_data: Any = None):
    """
    Decorator that provides fallback data when database operations fail.
    
    Args:
        fallback_data: Data to return when database operation fails
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except (DatabaseError, ChatDatabaseError) as e:
                log.warning(f"Database operation {func.__name__} failed, using fallback: {e}")
                chat_error_handler.record_fallback_usage(func.__name__, "database_fallback")
                return fallback_data
            except Exception as e:
                # Check if it's a database-related error by message content
                if "database" in str(e).lower() or "postgresql" in str(e).lower():
                    log.warning(f"Database operation {func.__name__} failed, using fallback: {e}")
                    chat_error_handler.record_fallback_usage(func.__name__, "database_fallback")
                    return fallback_data
                else:
                    raise
        
        return wrapper
    return decorator


def vector_store_fallback_decorator(fallback_operation: Optional[Callable] = None):
    """
    Decorator that provides fallback when vector store operations fail.
    
    Args:
        fallback_operation: Alternative operation to execute on vector store failure
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except (LLMError, ChatVectorStoreError) as e:
                if fallback_operation:
                    log.warning(f"Vector store operation {func.__name__} failed, using fallback: {e}")
                    chat_error_handler.record_fallback_usage(func.__name__, "vector_store_fallback")
                    
                    if asyncio.iscoroutinefunction(fallback_operation):
                        return await fallback_operation(*args, **kwargs)
                    else:
                        return fallback_operation(*args, **kwargs)
                else:
                    raise
            except Exception as e:
                # Check if it's a vector store-related error
                if "qdrant" in str(e).lower() or "vector" in str(e).lower():
                    if fallback_operation:
                        log.warning(f"Vector store operation {func.__name__} failed, using fallback: {e}")
                        chat_error_handler.record_fallback_usage(func.__name__, "vector_store_fallback")
                        
                        if asyncio.iscoroutinefunction(fallback_operation):
                            return await fallback_operation(*args, **kwargs)
                        else:
                            return fallback_operation(*args, **kwargs)
                    else:
                        raise
                else:
                    raise
        
        return wrapper
    return decorator