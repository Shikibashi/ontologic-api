"""
Cache helper utilities for consistent caching patterns across services.

Provides reusable caching logic to eliminate code duplication and ensure
consistent cache behavior across all services.
"""

from typing import TypeVar, Callable, Awaitable, Optional, Any, TYPE_CHECKING
from app.core.logger import log

if TYPE_CHECKING:
    from app.services.cache_service import RedisCacheService

T = TypeVar('T')


async def with_cache(
    cache_service: Optional['RedisCacheService'],
    cache_key_prefix: str,
    compute_fn: Callable[[], Awaitable[T]],
    ttl: int,
    *key_args: Any,
    return_cache_status: bool = False,
    **key_kwargs: Any
) -> T | tuple[T, bool]:
    """
    Generic caching wrapper for async functions.

    Follows the standard caching pattern:
    1. Check if cache_service exists (skip caching if None)
    2. Try to get from cache
    3. On cache miss, compute result
    4. Store result in cache
    5. Return result (and optionally cache hit status)

    Args:
        cache_service: Optional cache service instance (None = skip caching, graceful degradation)
        cache_key_prefix: Prefix for the cache key (e.g., 'embedding', 'splade', 'query')
        compute_fn: Async function to call on cache miss
        ttl: Time-to-live in seconds
        *key_args: Positional arguments used to generate cache key
        return_cache_status: If True, returns (result, was_cached) tuple for metrics tracking
        **key_kwargs: Keyword arguments used to generate cache key

    Returns:
        Cached result or computed result
        If return_cache_status=True, returns (result, was_cached) tuple

    Example:
        ```python
        # Simple usage (backward compatible)
        async def get_embedding(self, text: str):
            return await with_cache(
                cache_service=self._cache_service,
                cache_key_prefix='embedding',
                compute_fn=lambda: asyncio.to_thread(self.embed_model.get_general_text_embedding, text),
                ttl=86400,  # 24 hours
                text  # key argument
            )

        # With cache status for metrics (no double cache checking)
        async def get_embedding_with_metrics(self, text: str):
            result, was_cached = await with_cache(
                cache_service=self._cache_service,
                cache_key_prefix='embedding',
                compute_fn=lambda: asyncio.to_thread(self.embed_model.get_general_text_embedding, text),
                ttl=86400,
                return_cache_status=True,
                text
            )
            status = 'cached' if was_cached else 'success'
            # Track metrics with accurate status
            return result
        ```

    Note:
        Cache key must include ALL parameters that affect the result.
        For embeddings: only text matters
        For queries: text, collection, limit, vector_types, filter, and payload all matter
    """
    # Skip caching if service unavailable (graceful degradation)
    if cache_service is None:
        log.debug(f"Cache service unavailable for {cache_key_prefix}, computing without cache")

        # Add span event if tracing is available
        try:
            from app.core.tracing import add_span_event
            add_span_event("cache.unavailable", {
                "cache_type": cache_key_prefix,
                "reason": "cache_service is None"
            })
        except ImportError:
            pass  # Tracing not available, graceful degradation

        result = await compute_fn()
        return (result, False) if return_cache_status else result

    # Generate cache key from prefix and arguments
    cache_key = cache_service._make_cache_key(cache_key_prefix, *key_args, **key_kwargs)

    # Try cache first with explicit cache_type for accurate metrics
    cached_result = await cache_service.get(cache_key, cache_type=cache_key_prefix)

    if cached_result is not None:
        log.debug(f"Cache hit for {cache_key_prefix}")
        return (cached_result, True) if return_cache_status else cached_result

    # Cache miss - compute result
    log.debug(f"Cache miss for {cache_key_prefix}, computing result")
    result = await compute_fn()

    # Store in cache for future requests with explicit cache_type
    try:
        await cache_service.set(cache_key, result, ttl, cache_type=cache_key_prefix)
        log.debug(f"Stored {cache_key_prefix} in cache (TTL: {ttl}s)")
    except Exception as e:
        # Don't fail the request if cache storage fails
        log.warning(f"Failed to store {cache_key_prefix} in cache: {e}")

    return (result, False) if return_cache_status else result
