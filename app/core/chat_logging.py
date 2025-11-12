"""
Enhanced logging configuration for chat history operations.

This module provides structured logging with privacy protection,
performance tracking, and security compliance monitoring.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from functools import wraps

from app.core.logger import log


class ChatLogFilter(logging.Filter):
    """
    Custom logging filter for chat operations with privacy protection.
    
    Filters and sanitizes log records to ensure no sensitive information
    is logged while maintaining useful debugging information.
    """
    
    # Fields that should be redacted for privacy
    SENSITIVE_FIELDS = {
        'session_id', 'message_content', 'user_query', 'ai_response',
        'conversation_id', 'message_id', 'api_key', 'token', 'password'
    }
    
    # Fields that should be truncated if too long
    TRUNCATE_FIELDS = {
        'content': 200,
        'query': 100,
        'message': 500,
        'error_details': 1000
    }
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter and sanitize log records for privacy and security.
        
        Args:
            record: The log record to filter
            
        Returns:
            True to allow the record, False to block it
        """
        # Add chat-specific context
        if hasattr(record, 'operation'):
            record.chat_operation = record.operation
        
        # Sanitize extra fields if present
        if hasattr(record, '__dict__'):
            self._sanitize_record_data(record)
        
        # Add timestamp for chat operations
        record.chat_timestamp = datetime.now(timezone.utc).isoformat()
        
        return True
    
    def _sanitize_record_data(self, record: logging.LogRecord) -> None:
        """Sanitize sensitive data in log record."""
        for attr_name in dir(record):
            if attr_name.startswith('_'):
                continue
                
            attr_value = getattr(record, attr_name, None)
            
            # Sanitize sensitive fields
            if attr_name.lower() in self.SENSITIVE_FIELDS:
                if isinstance(attr_value, str) and len(attr_value) > 10:
                    # Keep first 3 and last 3 characters for debugging
                    setattr(record, attr_name, f"{attr_value[:3]}...{attr_value[-3:]}")
                else:
                    setattr(record, attr_name, "[REDACTED]")
            
            # Truncate long fields
            elif attr_name.lower() in self.TRUNCATE_FIELDS:
                max_length = self.TRUNCATE_FIELDS[attr_name.lower()]
                if isinstance(attr_value, str) and len(attr_value) > max_length:
                    setattr(record, attr_name, f"{attr_value[:max_length]}...[TRUNCATED]")
            
            # Sanitize dictionary values
            elif isinstance(attr_value, dict):
                setattr(record, attr_name, self._sanitize_dict(attr_value))
    
    def _sanitize_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively sanitize dictionary data."""
        sanitized = {}
        
        for key, value in data.items():
            if key.lower() in self.SENSITIVE_FIELDS:
                if isinstance(value, str) and len(value) > 10:
                    sanitized[key] = f"{value[:3]}...{value[-3:]}"
                else:
                    sanitized[key] = "[REDACTED]"
            elif key.lower() in self.TRUNCATE_FIELDS:
                max_length = self.TRUNCATE_FIELDS[key.lower()]
                if isinstance(value, str) and len(value) > max_length:
                    sanitized[key] = f"{value[:max_length]}...[TRUNCATED]"
                else:
                    sanitized[key] = value
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_dict(item) if isinstance(item, dict) else item
                    for item in value[:10]  # Limit list size in logs
                ]
            else:
                sanitized[key] = value
        
        return sanitized


class ChatPerformanceLogger:
    """
    Performance logging utility for chat operations.
    
    Tracks operation timing, resource usage, and performance metrics
    with structured logging for monitoring and analysis.
    """
    
    def __init__(self):
        self.active_operations: Dict[str, Dict[str, Any]] = {}
    
    def start_operation(self, operation_id: str, operation_name: str, 
                       context: Optional[Dict[str, Any]] = None) -> None:
        """Start tracking a chat operation."""
        self.active_operations[operation_id] = {
            'operation_name': operation_name,
            'start_time': datetime.now(timezone.utc),
            'context': context or {}
        }
        
        log.debug(f"Started chat operation: {operation_name}", extra={
            'operation_id': operation_id,
            'operation_name': operation_name,
            'context': context
        })
    
    def end_operation(self, operation_id: str, success: bool = True, 
                     result_summary: Optional[Dict[str, Any]] = None,
                     error_info: Optional[Dict[str, Any]] = None) -> float:
        """End tracking a chat operation and log performance metrics."""
        if operation_id not in self.active_operations:
            log.warning(f"Attempted to end unknown operation: {operation_id}")
            return 0.0
        
        operation_data = self.active_operations.pop(operation_id)
        end_time = datetime.now(timezone.utc)
        duration = (end_time - operation_data['start_time']).total_seconds() * 1000
        
        log_data = {
            'operation_id': operation_id,
            'operation_name': operation_data['operation_name'],
            'duration_ms': duration,
            'success': success,
            'start_time': operation_data['start_time'].isoformat(),
            'end_time': end_time.isoformat(),
            'context': operation_data['context']
        }
        
        if result_summary:
            log_data['result_summary'] = result_summary
        
        if error_info:
            log_data['error_info'] = error_info
        
        # Log at appropriate level based on success and duration
        if not success:
            log.error(f"Chat operation failed: {operation_data['operation_name']}", extra=log_data)
        elif duration > 5000:  # Slow operations (>5s)
            log.warning(f"Slow chat operation: {operation_data['operation_name']}", extra=log_data)
        elif duration > 2000:  # Moderately slow operations (>2s)
            log.info(f"Chat operation completed: {operation_data['operation_name']}", extra=log_data)
        else:
            log.debug(f"Chat operation completed: {operation_data['operation_name']}", extra=log_data)
        
        return duration
    
    def log_resource_usage(self, operation_name: str, resource_data: Dict[str, Any]) -> None:
        """Log resource usage for a chat operation."""
        log.info(f"Resource usage for {operation_name}", extra={
            'operation_name': operation_name,
            'resource_usage': resource_data,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })


class ChatSecurityLogger:
    """
    Security-focused logging for chat operations.
    
    Logs security events, privacy violations, and compliance-related
    activities with appropriate detail levels.
    """
    
    @staticmethod
    def log_privacy_violation(violation_type: str, session_id: Optional[str] = None,
                            details: Optional[Dict[str, Any]] = None) -> None:
        """Log a privacy violation incident."""
        log.critical("Privacy violation detected in chat system", extra={
            'event_type': 'privacy_violation',
            'violation_type': violation_type,
            'session_id': session_id[:8] + "..." if session_id else None,  # Partial session ID
            'details': details or {},
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'severity': 'critical'
        })
    
    @staticmethod
    def log_security_event(event_type: str, severity: str, description: str,
                          session_id: Optional[str] = None,
                          additional_data: Optional[Dict[str, Any]] = None) -> None:
        """Log a security-related event."""
        log_level = getattr(log, severity.lower(), log.info)
        
        log_level(f"Security event: {description}", extra={
            'event_type': 'security_event',
            'security_event_type': event_type,
            'severity': severity,
            'description': description,
            'session_id': session_id[:8] + "..." if session_id else None,
            'additional_data': additional_data or {},
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    @staticmethod
    def log_access_attempt(operation: str, session_id: str, success: bool,
                          reason: Optional[str] = None) -> None:
        """Log an access attempt to chat data."""
        log.info(f"Chat data access attempt: {operation}", extra={
            'event_type': 'access_attempt',
            'operation': operation,
            'session_id': session_id[:8] + "..." if session_id else None,
            'success': success,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })


class ChatComplianceLogger:
    """
    Compliance logging for chat operations.
    
    Logs activities required for regulatory compliance, audit trails,
    and data governance.
    """
    
    @staticmethod
    def log_data_retention_event(event_type: str, session_id: str,
                               data_summary: Dict[str, Any]) -> None:
        """Log data retention related events."""
        log.info(f"Data retention event: {event_type}", extra={
            'event_type': 'data_retention',
            'retention_event_type': event_type,
            'session_id': session_id[:8] + "..." if session_id else None,
            'data_summary': data_summary,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    @staticmethod
    def log_data_deletion(session_id: str, deletion_type: str,
                         items_deleted: Dict[str, int]) -> None:
        """Log data deletion for compliance tracking."""
        log.info(f"Chat data deletion: {deletion_type}", extra={
            'event_type': 'data_deletion',
            'deletion_type': deletion_type,
            'session_id': session_id[:8] + "..." if session_id else None,
            'items_deleted': items_deleted,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'compliance_event': True
        })
    
    @staticmethod
    def log_data_export(session_id: str, export_type: str,
                       data_summary: Dict[str, Any]) -> None:
        """Log data export for compliance tracking."""
        log.info(f"Chat data export: {export_type}", extra={
            'event_type': 'data_export',
            'export_type': export_type,
            'session_id': session_id[:8] + "..." if session_id else None,
            'data_summary': data_summary,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'compliance_event': True
        })


# Global logger instances
chat_performance_logger = ChatPerformanceLogger()
chat_security_logger = ChatSecurityLogger()
chat_compliance_logger = ChatComplianceLogger()


def setup_chat_logging() -> None:
    """
    Set up enhanced logging configuration for chat operations.
    
    Adds custom filters and formatters to ensure privacy protection
    and structured logging for monitoring and compliance.
    """
    # Add chat log filter to the main logger
    chat_filter = ChatLogFilter()
    
    # Get the root logger and add our filter
    root_logger = logging.getLogger()
    root_logger.addFilter(chat_filter)
    
    # Also add to the app logger specifically
    app_logger = logging.getLogger('app')
    app_logger.addFilter(chat_filter)
    
    log.info("Chat logging configuration applied with privacy protection")


def log_chat_operation(operation_name: str, include_performance: bool = True):
    """
    Decorator to automatically log chat operations with performance tracking.
    
    Args:
        operation_name: Name of the operation to log
        include_performance: Whether to include performance tracking
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            operation_id = f"{operation_name}_{datetime.now(timezone.utc).timestamp()}"
            
            # Extract session_id from kwargs if available
            session_id = kwargs.get('session_id')
            context = {
                'session_id': session_id[:8] + "..." if session_id else None,
                'function': func.__name__,
                'args_count': len(args),
                'kwargs_keys': list(kwargs.keys())
            }
            
            if include_performance:
                chat_performance_logger.start_operation(operation_id, operation_name, context)
            
            try:
                result = await func(*args, **kwargs)
                
                if include_performance:
                    result_summary = {
                        'result_type': type(result).__name__,
                        'result_size': len(result) if hasattr(result, '__len__') else None
                    }
                    chat_performance_logger.end_operation(
                        operation_id, success=True, result_summary=result_summary
                    )
                
                return result
                
            except Exception as e:
                error_info = {
                    'error_type': type(e).__name__,
                    'error_message': str(e)[:200]  # Truncate long error messages
                }
                
                if include_performance:
                    chat_performance_logger.end_operation(
                        operation_id, success=False, error_info=error_info
                    )
                
                # Log security events for certain error types
                if 'privacy' in str(e).lower() or 'unauthorized' in str(e).lower():
                    chat_security_logger.log_security_event(
                        event_type='operation_error',
                        severity='warning',
                        description=f"Security-related error in {operation_name}",
                        session_id=session_id,
                        additional_data=error_info
                    )
                
                raise
        
        return wrapper
    return decorator


# Initialize chat logging on module import
setup_chat_logging()