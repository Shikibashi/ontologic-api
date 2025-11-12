"""
Application-wide constants to replace magic numbers and improve maintainability.

All numeric literals and configuration values should be defined here with clear documentation.
"""

from typing import Final

# ============================================================================
# Context Window Configuration
# ============================================================================

DEFAULT_CONTEXT_WINDOW: Final[int] = 8192
"""Default LLM context window size in tokens."""

MAX_CONTEXT_WINDOW: Final[int] = 32768
"""Maximum LLM context window size in tokens."""

MIN_CONTEXT_WINDOW: Final[int] = 512
"""Minimum recommended context window size in tokens."""

CONTEXT_BUFFER_TOKENS: Final[int] = 2000
"""Buffer tokens reserved for system prompts and response generation."""

CHARS_PER_TOKEN_ESTIMATE: Final[int] = 4
"""Rough approximation of characters per token for context estimation."""


# ============================================================================
# Chat History Configuration
# ============================================================================

AVERAGE_MESSAGE_LENGTH_CHARS: Final[int] = 200
"""Average length of a chat message in characters."""

CHAT_CONTEXT_WINDOW_CHARS: Final[int] = 4000
"""Character limit for conversation history context window."""

MAX_CONVERSATION_HISTORY_MESSAGES: Final[int] = 50
"""Maximum number of messages to include in conversation history."""


# ============================================================================
# Caching Configuration
# ============================================================================

IN_MEMORY_CACHE_MAX_SIZE: Final[int] = 50
"""Maximum number of entries in legacy in-memory caches (deprecated)."""

CACHE_TTL_SECONDS: Final[int] = 3600
"""Default cache TTL in seconds (1 hour)."""

LLM_QUERY_CACHE_TTL: Final[int] = 3600
"""Cache TTL for LLM query results (1 hour)."""

EMBEDDING_CACHE_TTL: Final[int] = 86400
"""Cache TTL for embeddings (24 hours)."""

PHILOSOPHER_COLLECTIONS_CACHE_TTL: Final[int] = 3600
"""Cache TTL for philosopher collections (1 hour - collections rarely change)."""


# ============================================================================
# Cache Key Constants
# ============================================================================

CACHE_KEY_PHILOSOPHER_COLLECTIONS: Final[str] = "philosopher_collections"
"""Standard cache key for philosopher collections list."""


# ============================================================================
# PDF Context Configuration
# ============================================================================

DEFAULT_PDF_CONTEXT_LIMIT: Final[int] = 5
"""Default number of PDF context chunks to retrieve."""

MAX_PDF_CONTEXT_LIMIT: Final[int] = 20
"""Maximum number of PDF context chunks allowed."""


# ============================================================================
# Qdrant Query Configuration
# ============================================================================

DEFAULT_QUERY_LIMIT: Final[int] = 10
"""Default number of results to retrieve from Qdrant."""

MAX_QUERY_LIMIT: Final[int] = 100
"""Maximum number of results allowed from Qdrant."""

META_REFEED_LIMIT: Final[int] = 10
"""Number of results to retrieve during meta collection refeed."""


# ============================================================================
# Timeout Configuration (Fallback Values)
# ============================================================================

DEFAULT_LLM_TIMEOUT_SECONDS: Final[int] = 120
"""Default timeout for LLM operations when not specified in config."""

DEFAULT_QDRANT_TIMEOUT_SECONDS: Final[int] = 30
"""Default timeout for Qdrant operations when not specified in config."""

DEFAULT_HTTP_TIMEOUT_SECONDS: Final[int] = 30
"""Default timeout for HTTP requests."""

STREAM_INIT_TIMEOUT_SECONDS: Final[int] = 5
"""Timeout for initializing streaming responses."""

UVICORN_KEEPALIVE_TIMEOUT_SECONDS: Final[int] = 600
"""Uvicorn keep-alive timeout for long-running LLM operations (10 minutes)."""

UVICORN_GRACEFUL_SHUTDOWN_SECONDS: Final[int] = 30
"""Uvicorn graceful shutdown timeout."""


# ============================================================================
# Rate Limiting Configuration
# ============================================================================

RATE_LIMIT_ASK_PHILOSOPHY: Final[str] = "10/minute"
"""Rate limit for philosophy question endpoints (expensive operations)."""

RATE_LIMIT_ASK_PHILOSOPHY_HOURLY: Final[str] = "100/hour"
"""Hourly rate limit for philosophy questions (burst protection)."""

RATE_LIMIT_PDF_CONTEXT: Final[str] = "2/minute"
"""Rate limit for PDF context queries (5x more expensive)."""

RATE_LIMIT_ASK_SIMPLE: Final[str] = "30/minute"
"""Rate limit for simple LLM queries."""

RATE_LIMIT_QUERY_HYBRID: Final[str] = "20/minute"
"""Rate limit for hybrid search queries."""

RATE_LIMIT_GET_PHILOSOPHERS: Final[str] = "60/minute"
"""Rate limit for philosopher listing (cheap operation)."""


# ============================================================================
# Database Configuration
# ============================================================================

DATABASE_POOL_SIZE: Final[int] = 10
"""Database connection pool size."""

DATABASE_MAX_OVERFLOW: Final[int] = 20
"""Maximum overflow connections beyond pool size."""


# ============================================================================
# Security Configuration
# ============================================================================

MAX_UPLOAD_SIZE_MB: Final[int] = 50
"""Maximum file upload size in megabytes."""

JWT_ALGORITHM: Final[str] = "HS256"
"""JWT signing algorithm."""


# ============================================================================
# Validation Limits
# ============================================================================

MIN_QUERY_LENGTH: Final[int] = 1
"""Minimum query string length."""

MAX_QUERY_LENGTH: Final[int] = 10000
"""Maximum query string length."""

MIN_TEMPERATURE: Final[float] = 0.0
"""Minimum temperature value for LLM."""

MAX_TEMPERATURE: Final[float] = 1.0
"""Maximum temperature value for LLM."""


# ============================================================================
# LLM Generation Configuration
# ============================================================================

DEFAULT_LLM_TEMPERATURE: Final[float] = 0.3
"""Default LLM temperature for balanced creativity and consistency."""

DEFAULT_LLM_TOP_P: Final[float] = 0.9
"""Default nucleus sampling parameter for faster generation."""

DEFAULT_LLM_TOP_K: Final[int] = 40
"""Default top-k sampling to limit token choices for speed."""

DEFAULT_LLM_NUM_PREDICT: Final[int] = 512
"""Default maximum response length in tokens."""

MAX_NODES_FOR_CONTEXT: Final[int] = 15
"""Maximum number of nodes to include in context window."""


# ============================================================================
# Chat History Cleanup Configuration
# ============================================================================

CLEANUP_SAFETY_THRESHOLD: Final[int] = 100
"""Safety threshold for conversation cleanup operations."""
