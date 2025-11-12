import asyncio
import time
from typing import Dict, Any, List, Optional, Callable, TypeVar, Generic
from functools import wraps
from collections import defaultdict
import hashlib
import json

from app.core.logger import log


T = TypeVar('T')


class AsyncBatcher(Generic[T]):
    """
    Batches async operations to improve performance.

    Collects multiple similar requests and processes them together
    to reduce overhead and improve throughput.
    """

    def __init__(
        self,
        batch_processor: Callable[[List[T]], List[Any]],
        max_batch_size: int = 10,
        max_wait_time: float = 0.1
    ):
        self.batch_processor = batch_processor
        self.max_batch_size = max_batch_size
        self.max_wait_time = max_wait_time
        self.pending_items: List[T] = []
        self.pending_futures: List[asyncio.Future] = []
        self.processing_task: Optional[asyncio.Task] = None

    async def submit(self, item: T) -> Any:
        """Submit an item for batch processing."""
        future = asyncio.Future()

        self.pending_items.append(item)
        self.pending_futures.append(future)

        # Start processing if batch is full or no processing task exists
        if len(self.pending_items) >= self.max_batch_size or not self.processing_task:
            if self.processing_task:
                self.processing_task.cancel()
            self.processing_task = asyncio.create_task(self._process_batch())

        return await future

    async def _process_batch(self):
        """Process the current batch after max_wait_time."""
        await asyncio.sleep(self.max_wait_time)

        if not self.pending_items:
            return

        items = self.pending_items.copy()
        futures = self.pending_futures.copy()

        self.pending_items.clear()
        self.pending_futures.clear()

        try:
            results = await self.batch_processor(items)

            # Distribute results to futures
            for future, result in zip(futures, results):
                if not future.cancelled():
                    future.set_result(result)

        except Exception as e:
            # Set exception for all futures
            for future in futures:
                if not future.cancelled():
                    future.set_exception(e)


class CacheManager:
    """
    DEPRECATED: Use RedisCacheService via dependency injection instead.

    This in-memory cache manager is retained for backward compatibility
    but will be removed in a future version. New code should use Redis-backed
    caching which provides distributed caching and persistence.

    Migration guide:
        # OLD (don't do this):
        from app.services.cache_service import RedisCacheService
        cache = RedisCacheService()  # ❌ Creates singleton, violates DI pattern

        # NEW (correct pattern):
        from app.core.dependencies import CacheServiceDep

        # In router/endpoint:
        async def my_endpoint(cache_service: CacheServiceDep):
            if cache_service is not None:
                result = await cache_service.get(key, cache_type='your_cache_type')

        # In service __init__:
        def __init__(self, cache_service: Optional['RedisCacheService'] = None):
            self._cache_service = cache_service

    Simple in-memory cache with TTL support for performance optimization.
    Provides caching hooks for expensive operations like query expansion
    and LLM responses.
    """

    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl

    def _make_key(self, prefix: str, *args, **kwargs) -> str:
        """Create a cache key from arguments."""
        # Create a deterministic key from arguments
        key_data = {
            'args': args,
            'kwargs': sorted(kwargs.items()) if kwargs else {}
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"{prefix}:{key_hash}"

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key not in self.cache:
            return None

        cache_entry = self.cache[key]
        current_time = time.time()

        if current_time > cache_entry['expires_at']:
            del self.cache[key]
            return None

        cache_entry['last_accessed'] = current_time
        return cache_entry['value']

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL."""
        if ttl is None:
            ttl = self.default_ttl

        current_time = time.time()
        self.cache[key] = {
            'value': value,
            'created_at': current_time,
            'last_accessed': current_time,
            'expires_at': current_time + ttl
        }

    def cached(self, prefix: str, ttl: Optional[int] = None):
        """Decorator for caching function results."""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                cache_key = self._make_key(prefix, *args, **kwargs)
                cached_result = self.get(cache_key)

                if cached_result is not None:
                    log.debug(f"Cache hit for {prefix}: {cache_key[:20]}...")
                    return cached_result

                result = await func(*args, **kwargs)
                self.set(cache_key, result, ttl)
                log.debug(f"Cache miss for {prefix}: {cache_key[:20]}...")
                return result

            return wrapper
        return decorator

    def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all cache entries with given prefix."""
        keys_to_remove = [key for key in self.cache.keys() if key.startswith(prefix)]

        for key in keys_to_remove:
            del self.cache[key]

        return len(keys_to_remove)

    def cleanup_expired(self) -> int:
        """Remove expired cache entries."""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self.cache.items()
            if current_time > entry['expires_at']
        ]

        for key in expired_keys:
            del self.cache[key]

        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        current_time = time.time()
        valid_entries = sum(
            1 for entry in self.cache.values()
            if current_time <= entry['expires_at']
        )

        return {
            'total_entries': len(self.cache),
            'valid_entries': valid_entries,
            'expired_entries': len(self.cache) - valid_entries,
            'cache_prefixes': list(set(key.split(':')[0] for key in self.cache.keys())),
            'memory_usage_estimate': sum(
                len(str(entry['value'])) for entry in self.cache.values()
            )
        }


class PerformanceConfig:
    """Configuration for performance optimizations."""

    def __init__(self):
        # RRF configuration
        self.rrf_k_default = 60
        self.rrf_k_min = 1
        self.rrf_k_max = 1000

        # Batching configuration
        self.max_batch_size = 10
        self.max_batch_wait_time = 0.1

        # Cache configuration
        self.cache_ttl_default = 300  # 5 minutes
        self.cache_ttl_expansion = 600  # 10 minutes for expansion results
        self.cache_ttl_retrieval = 180  # 3 minutes for retrieval results

        # Async configuration
        self.max_concurrent_expansions = 5
        self.max_concurrent_retrievals = 10

    def validate_rrf_k(self, k: int) -> int:
        """Validate and clamp RRF k parameter."""
        return max(self.rrf_k_min, min(self.rrf_k_max, k))

    def get_cache_ttl(self, operation_type: str) -> int:
        """Get appropriate cache TTL for operation type."""
        ttl_map = {
            'expansion': self.cache_ttl_expansion,
            'retrieval': self.cache_ttl_retrieval,
            'default': self.cache_ttl_default
        }
        return ttl_map.get(operation_type, self.cache_ttl_default)


class PerformanceMonitor:
    """Monitor and track performance metrics."""

    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)
        self.counters: Dict[str, int] = defaultdict(int)

    def time_operation(self, operation_name: str):
        """Decorator to time operations."""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    self.counters[f"{operation_name}_success"] += 1
                    return result
                except Exception as e:
                    self.counters[f"{operation_name}_error"] += 1
                    raise
                finally:
                    duration = time.time() - start_time
                    self.metrics[operation_name].append(duration)
                    # Keep only last 100 measurements
                    if len(self.metrics[operation_name]) > 100:
                        self.metrics[operation_name] = self.metrics[operation_name][-100:]

            return wrapper
        return decorator

    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        stats = {'counters': dict(self.counters)}

        for operation, times in self.metrics.items():
            if times:
                stats[operation] = {
                    'count': len(times),
                    'avg_time': sum(times) / len(times),
                    'min_time': min(times),
                    'max_time': max(times),
                    'total_time': sum(times)
                }

        return stats


# Global instances
cache_manager = CacheManager()
performance_config = PerformanceConfig()
performance_monitor = PerformanceMonitor()


# Convenience decorators
def cached_expansion(ttl: Optional[int] = None):
    """
    DEPRECATED: Use RedisCacheService.cache_query_results() instead.

    Cache expansion results.
    """
    import warnings
    warnings.warn(
        "cached_expansion is deprecated, use RedisCacheService.cache_query_results() instead",
        DeprecationWarning,
        stacklevel=2
    )
    return cache_manager.cached("expansion", ttl or performance_config.cache_ttl_expansion)


def cached_retrieval(ttl: Optional[int] = None):
    """
    DEPRECATED: Use RedisCacheService.cache_query_results() instead.

    Cache retrieval results.
    """
    import warnings
    warnings.warn(
        "cached_retrieval is deprecated, use RedisCacheService.cache_query_results() instead",
        DeprecationWarning,
        stacklevel=2
    )
    return cache_manager.cached("retrieval", ttl or performance_config.cache_ttl_retrieval)


def timed(operation_name: str):
    """Time an operation."""
    return performance_monitor.time_operation(operation_name)