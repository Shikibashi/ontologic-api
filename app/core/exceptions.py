"""Simplified custom exceptions for the ontologic API.

Only includes exceptions that are actually used in the codebase.
"""

from typing import Optional, Dict, Any


class OntologicError(Exception):
    """Base exception for ontologic API errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


# LLM-related exceptions (actually used)
class LLMError(OntologicError):
    """Base class for LLM-related errors."""
    pass


class LLMUnavailableError(LLMError):
    """Raised when LLM service is unavailable."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when LLM request times out."""
    pass


class LLMResponseError(LLMError):
    """Raised when LLM returns invalid or unparseable response."""
    pass


class EmbeddingWarmupError(LLMError):
    """Raised when embedding generation fails during cache warming."""

    def __init__(self, message: str = "Embedding warmup failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)


# Query expansion exceptions (actually used)
class ExpansionMethodError(OntologicError):
    """Raised when a specific expansion method fails."""

    def __init__(self, method: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.method = method
        super().__init__(f"Expansion method '{method}' failed: {message}", details)


# Workflow exceptions (actually used)
class WorkflowError(OntologicError):
    """Base class for workflow-related errors."""
    pass


class DraftNotFoundError(WorkflowError):
    """Raised when a draft is not found."""

    def __init__(self, draft_id: str):
        self.draft_id = draft_id
        super().__init__(f"Draft not found: {draft_id}")


class GenerationError(WorkflowError):
    """Raised when content generation fails."""
    pass


class ReviewError(WorkflowError):
    """Raised when review process fails."""
    pass


# Validation exceptions (heavily used)
class ValidationError(OntologicError):
    """Raised when input validation fails."""
    pass


# Security exceptions (used in security module)
class SecurityError(OntologicError):
    """Raised when security validation fails."""
    pass


# Database exceptions (used in database operations)
class DatabaseError(OntologicError):
    """Raised when database operations fail."""
    pass


class CacheOperationError(OntologicError):
    """Raised when cache operations fail (e.g., Redis connectivity or writes)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, details)


# Service dependency exceptions (used during service initialization)
class DependencyUnavailableError(OntologicError):
    """Raised when a required service dependency is not available."""

    def __init__(self, message: str, dependency_name: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.dependency_name = dependency_name
        super().__init__(message, details)
