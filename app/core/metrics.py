"""
Custom Prometheus Metrics for Ontologic API.

This module defines application-specific metrics for monitoring:
- LLM query performance and token usage
- Cache hit/miss rates for embeddings and queries
- Qdrant vector search performance
- Chat history operations

Metrics are exposed via the /metrics endpoint alongside standard HTTP metrics.
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from typing import Optional, Callable, Any
import time
import inspect
from functools import wraps
from app.core.logger import log


# ========== LLM Metrics ==========

llm_query_duration_seconds = Histogram(
    'llm_query_duration_seconds',
    'Duration of LLM queries in seconds',
    ['model', 'operation_type', 'status'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)

llm_query_tokens_total = Counter(
    'llm_query_tokens_total',
    'Total number of tokens processed by LLM',
    ['model', 'token_type']  # token_type: prompt, completion, total
)

llm_query_total = Counter(
    'llm_query_total',
    'Total number of LLM queries',
    ['model', 'operation_type', 'status']  # status: success, error, timeout
)

llm_embedding_duration_seconds = Histogram(
    'llm_embedding_duration_seconds',
    'Duration of embedding generation in seconds',
    ['model', 'status'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0)
)

llm_splade_duration_seconds = Histogram(
    'llm_splade_duration_seconds',
    'Duration of SPLADE vector generation in seconds',
    ['model', 'status'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0)
)


# ========== Cache Metrics ==========

cache_operations_total = Counter(
    'cache_operations_total',
    'Total number of cache operations',
    ['operation', 'cache_type', 'status']  # operation: get, set; cache_type: embedding, splade, query; status: hit, miss, error
)

cache_hit_rate = Gauge(
    'cache_hit_rate',
    'Cache hit rate percentage',
    ['cache_type']  # cache_type: embedding, splade, query, overall
)

cache_size_bytes = Gauge(
    'cache_size_bytes',
    'Estimated cache size in bytes',
    ['cache_type']
)

cache_ttl_seconds = Gauge(
    'cache_ttl_seconds',
    'Cache TTL configuration in seconds',
    ['cache_type']
)


# ========== Qdrant Metrics ==========

qdrant_query_duration_seconds = Histogram(
    'qdrant_query_duration_seconds',
    'Duration of Qdrant queries in seconds',
    ['collection', 'query_type', 'status'],  # query_type: hybrid, dense, sparse, fusion
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
)

qdrant_query_results_total = Histogram(
    'qdrant_query_results_total',
    'Number of results returned by Qdrant queries',
    ['collection', 'query_type'],
    buckets=(1, 5, 10, 20, 50, 100, 200)
)

qdrant_query_total = Counter(
    'qdrant_query_total',
    'Total number of Qdrant queries',
    ['collection', 'query_type', 'status']  # status: success, error, timeout
)

qdrant_collection_points = Gauge(
    'qdrant_collection_points',
    'Number of points in Qdrant collection',
    ['collection']
)


# ========== Subscription Metrics ==========

subscription_fail_open_mode = Gauge(
    'subscription_fail_open_mode',
    'Whether subscription fail-open mode is active (1=enabled, 0=disabled)'
)


# ========== Chat History Metrics ==========

chat_operations_total = Counter(
    'chat_operations_total',
    'Total number of chat history operations',
    ['operation', 'status']  # operation: store_message, get_history, search; status: success, error
)

chat_message_size_bytes = Histogram(
    'chat_message_size_bytes',
    'Size of chat messages in bytes',
    ['role'],  # role: user, assistant, system
    buckets=(100, 500, 1000, 5000, 10000, 50000)
)

chat_session_duration_seconds = Histogram(
    'chat_session_duration_seconds',
    'Duration of chat sessions in seconds',
    buckets=(60, 300, 600, 1800, 3600, 7200, 14400)  # 1min to 4hrs
)


# ========== Cache Warming Metrics ==========

cache_warming_duration_seconds = Histogram(
    'cache_warming_duration_seconds',
    'Duration of cache warming operations in seconds',
    ['warming_type', 'status'],  # warming_type: collections, embeddings, overall; status: success, error
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

cache_warming_items_total = Counter(
    'cache_warming_items_total',
    'Total number of items warmed in cache',
    ['warming_type', 'status']  # warming_type: collections, embeddings; status: success, error
)

cache_warming_operations_total = Counter(
    'cache_warming_operations_total',
    'Total number of cache warming operations',
    ['warming_type', 'status']  # warming_type: collections, embeddings, overall; status: success, error, skipped
)


# ========== System Info ==========

ontologic_info = Info(
    'ontologic_api',
    'Ontologic API version and configuration information'
)


# ========== Helper Functions ==========

def track_llm_query(model: str, operation_type: str = 'query'):
    """
    Decorator to track LLM query metrics.

    Args:
        model: LLM model name
        operation_type: Type of operation (query, stream, embedding, splade)

    Example:
        @track_llm_query(model='qwen3:8b', operation_type='query')
        async def aquery(self, question: str, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = 'success'

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start_time
                llm_query_duration_seconds.labels(
                    model=model,
                    operation_type=operation_type,
                    status=status
                ).observe(duration)
                llm_query_total.labels(
                    model=model,
                    operation_type=operation_type,
                    status=status
                ).inc()

        return wrapper
    return decorator


def track_cache_operation(cache_type: str):
    """
    Track cache hit/miss metrics.

    Args:
        cache_type: Type of cache (embedding, splade, query)

    Returns:
        Context manager for tracking cache operations
    """
    class CacheTracker:
        def __init__(self, cache_type: str):
            self.cache_type = cache_type

        def record_hit(self):
            cache_operations_total.labels(
                operation='get',
                cache_type=self.cache_type,
                status='hit'
            ).inc()

        def record_miss(self):
            cache_operations_total.labels(
                operation='get',
                cache_type=self.cache_type,
                status='miss'
            ).inc()

        def record_set(self):
            cache_operations_total.labels(
                operation='set',
                cache_type=self.cache_type,
                status='success'
            ).inc()

        def record_error(self):
            cache_operations_total.labels(
                operation='get',
                cache_type=self.cache_type,
                status='error'
            ).inc()

    return CacheTracker(cache_type)


def track_qdrant_query(collection: str = 'dynamic', query_type: str = 'hybrid'):
    """
    Decorator to track Qdrant query metrics.

    Args:
        collection: Qdrant collection name (use 'dynamic' to extract from function signature)
        query_type: Type of query (hybrid, dense, sparse, fusion)

    Example:
        @track_qdrant_query(collection='dynamic', query_type='hybrid')
        async def query_hybrid(self, query_text: str, collection: str, ...):
            # Collection parameter will be extracted reliably
            ...

    Note: When using 'dynamic', the decorated function MUST have a 'collection' parameter.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract actual collection name if 'dynamic'
            actual_collection = collection

            if collection == 'dynamic':
                # Use signature inspection for robust parameter extraction
                try:
                    sig = inspect.signature(func)
                    bound_args = sig.bind(*args, **kwargs)
                    bound_args.apply_defaults()

                    # Get collection parameter reliably
                    actual_collection = bound_args.arguments.get('collection', 'unknown')

                    if actual_collection == 'unknown':
                        log.warning(
                            f"Could not extract collection from {func.__name__} - "
                            f"metrics will be labeled 'unknown'. "
                            f"Ensure function has 'collection' parameter."
                        )
                except Exception as e:
                    log.warning(
                        f"Failed to extract collection from {func.__name__}: {e} - "
                        f"using 'unknown'"
                    )
                    actual_collection = 'unknown'

            start_time = time.time()
            status = 'success'
            result_count = 0

            try:
                result = await func(*args, **kwargs)

                # Count results
                if isinstance(result, dict):
                    result_count = sum(len(v) for v in result.values() if isinstance(v, list))
                elif isinstance(result, list):
                    result_count = len(result)

                qdrant_query_results_total.labels(
                    collection=actual_collection,
                    query_type=query_type
                ).observe(result_count)

                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start_time
                qdrant_query_duration_seconds.labels(
                    collection=actual_collection,
                    query_type=query_type,
                    status=status
                ).observe(duration)
                qdrant_query_total.labels(
                    collection=actual_collection,
                    query_type=query_type,
                    status=status
                ).inc()

        return wrapper
    return decorator


def update_cache_hit_rate(cache_type: str, hit_rate: float):
    """
    Update cache hit rate gauge.

    Args:
        cache_type: Type of cache (embedding, splade, query, overall)
        hit_rate: Hit rate as a percentage (0-100)
    """
    cache_hit_rate.labels(cache_type=cache_type).set(hit_rate)


def track_cache_warming(warming_type: str = 'overall', items_count: int = 1, items_count_fn: Optional[Callable[[Any], int]] = None):
    """
    Decorator to track cache warming metrics.

    Automatically tracks:
    - Operation duration (cache_warming_duration_seconds)
    - Success/failure status (cache_warming_operations_total)
    - Number of items warmed (cache_warming_items_total)

    Args:
        warming_type: Type of warming operation (collections, embeddings, overall)
        items_count: Default number of items (used as fallback or when no fn provided)
        items_count_fn: Optional function to extract count from result.
                       NOTE: This lambda receives the RETURN VALUE of the decorated function,
                       unlike track_llm_query which uses lambdas to extract configuration
                       from the instance at decoration time. If the function raises an
                       exception or returns None, falls back to items_count.

    Item Counting Behavior:
        - If result is None (error/no return): count = 0
        - If items_count_fn provided: count = items_count_fn(result) or items_count (fallback)
        - If result is int (auto-detected): count = result
        - Otherwise: count = items_count

    Example:
        # Returns int directly - auto-detected, no lambda needed
        @track_cache_warming(warming_type='collections')
        async def _warm_philosopher_collections(self) -> int:
            return 5  # Auto-detected as int, count = 5

        # Returns list - lambda extracts count from result
        @track_cache_warming(warming_type='embeddings', items_count_fn=lambda result: len(result))
        async def _warm_embeddings(self) -> List[str]:
            return [...]  # Lambda receives this list, count = len(list)

        # No item tracking (operation-level only)
        @track_cache_warming(warming_type='overall')
        async def warm_cache(self):
            ...  # Only duration/success tracked, no items
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            status = 'success'
            result = None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start_time
                cache_warming_duration_seconds.labels(
                    warming_type=warming_type,
                    status=status
                ).observe(duration)
                cache_warming_operations_total.labels(
                    warming_type=warming_type,
                    status=status
                ).inc()

                # Resolve items count
                count = 0

                # If we have a result, try to extract count
                if result is not None:
                    if items_count_fn is not None:
                        try:
                            extracted = items_count_fn(result)
                            count = extracted if extracted is not None else items_count
                        except Exception as e:
                            # Log extraction errors for debugging, fall back to default
                            log.warning(
                                f"Failed to extract item count using items_count_fn: {e}",
                                extra={
                                    "warming_type": warming_type,
                                    "function": func.__name__,
                                    "fallback_count": items_count
                                }
                            )
                            count = items_count
                    elif isinstance(result, int):
                        # Auto-detect: if no extraction function and result is int, use it directly
                        count = result
                    else:
                        count = items_count

                # Only increment metric if we have items
                if count > 0:
                    cache_warming_items_total.labels(
                        warming_type=warming_type,
                        status=status
                    ).inc(count)

        return wrapper
    return decorator


def initialize_metrics(version: str = '1.0.0', environment: str = 'dev'):
    """
    Initialize system info metrics.

    Args:
        version: API version
        environment: Deployment environment (dev, prod)
    """
    ontologic_info.info({
        'version': version,
        'environment': environment,
        'metrics_enabled': 'true'
    })

    log.info(f"Custom Prometheus metrics initialized for Ontologic API v{version} ({environment})")


def log_metrics_summary():
    """
    Log a summary of registered custom metrics.
    """
    metrics_count = {
        'llm_metrics': 5,
        'cache_metrics': 4,
        'qdrant_metrics': 4,
        'subscription_metrics': 1,
        'chat_metrics': 3,
        'cache_warming_metrics': 3,
        'system_info': 1
    }

    log.info("Custom Prometheus metrics registered:")
    for category, count in metrics_count.items():
        log.info(f"  - {category}: {count} metrics")
    log.info("Metrics available at /metrics endpoint")
