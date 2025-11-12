"""
Redis-based caching service for expensive operations.

Use dependency injection via `app.core.dependencies.get_cache_service()` to obtain
the lifespan-managed instance from app.state.

Provides distributed caching for:
- Embeddings (24h TTL)
- SPLADE vectors (24h TTL)
- Query results (1h TTL)

Features:
- Async Redis client with connection pooling
- Graceful degradation when Redis unavailable
- Secure JSON-only serialization (no pickle)
- Custom encoder for Pydantic models and numpy arrays
- Cache hit/miss metrics and logging

Usage (RECOMMENDED - with_cache helper):
    from app.core.cache_helpers import with_cache

    # In service constructors, accept cache_service via dependency injection:
    def __init__(self, cache_service: RedisCacheService = None):
        self._cache_service = cache_service

    # In methods, use with_cache helper for automatic key generation and error handling:
    async def get_expensive_data(self, arg1: str, arg2: int):
        return await with_cache(
            self._cache_service,
            'my_prefix',
            lambda: self._compute_expensive_data(arg1, arg2),
            ttl=3600,
            arg1,
            arg2
        )

Usage (Advanced - manual caching for special cases):
    # For complex caching logic not suitable for with_cache helper:
    # IMPORTANT: Always pass explicit cache_type for accurate metrics
    if self._cache_service is not None:
        cache_key = self._cache_service._make_cache_key('prefix', arg1, arg2)
        cached = await self._cache_service.get(cache_key, cache_type='your_cache_type')
        if cached is not None:
            return cached

    # ... compute result ...

    if self._cache_service is not None:
        await self._cache_service.set(cache_key, result, ttl, cache_type='your_cache_type')
"""

import asyncio
from datetime import date, datetime
import hashlib
import json
import os
import threading
import uuid
from functools import wraps
from importlib import import_module
from typing import Any, Callable, Dict, Optional

import redis.asyncio as redis

from app.config.settings import get_settings
from app.core.metrics import (
    cache_operations_total,
    cache_hit_rate,
    cache_size_bytes,
    cache_ttl_seconds,
    update_cache_hit_rate
)
from app.core.logger import log
from app.core.constants import EMBEDDING_CACHE_TTL, LLM_QUERY_CACHE_TTL
from app.core.tracing import trace_async_operation, set_span_attributes, add_span_event
from app.core.http_error_guard import with_retry
from app.core.timeout_helpers import calculate_per_attempt_timeout
from pydantic import BaseModel


# SECURITY: Custom JSON encoder prevents pickle-based RCE vulnerabilities (CVE-style attacks)
class SafeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for safe serialization without pickle.

    SECURITY: Uses JSON serialization exclusively to prevent pickle-based RCE vulnerabilities.
    Supports Pydantic models, numpy arrays, datetime/date objects, UUIDs, sets, and bytes
    by converting them into JSON-compatible representations.
    """

    def default(self, obj):
        # Handle Pydantic v2 models by using model_dump()
        if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
            return obj.model_dump()

        # Handle Pydantic v1 models via dict()
        if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
            return obj.dict()

        # Handle objects like numpy arrays via tolist()
        if hasattr(obj, "tolist") and callable(getattr(obj, "tolist")):
            return obj.tolist()

        # Convert datetime/date objects to ISO formatted strings
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()

        # Represent UUIDs as strings
        if isinstance(obj, uuid.UUID):
            return str(obj)

        # Convert sets into lists for JSON compatibility
        if isinstance(obj, set):
            return list(obj)

        # Decode bytes into UTF-8 strings, replacing errors safely
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")

        return super().default(obj)

    # Testing notes:
    # - Pydantic models (ScoredPoint from Qdrant) should serialize via model_dump()
    # - Numpy arrays should serialize via tolist()
    # - Standard Python types (list, dict, str, int, float, bool, None) work natively
    # - Legacy pickle-cached data will result in cache misses (acceptable for security)


class RedisCacheService:
    """Redis cache service with async support and secure JSON-only serialization.

    Security: Uses JSON serialization exclusively to prevent pickle-based RCE vulnerabilities.
    Supports Pydantic models, numpy arrays, and other common Python types via SafeJSONEncoder.

    This service is managed by the application lifespan and injected into other services
    via dependency injection. Access via app.core.dependencies.get_cache_service().
    """

    def __init__(self):
        """Initialize Redis cache service with configuration. Called once per instance."""
        self._redis_client = None
        self._redis_available = False
        # Thread-safe counter lock for concurrent access within this instance
        self._stats_lock = threading.Lock()
        self._config = {}
        self._hits = 0
        self._misses = 0
        self._errors = 0
        # Add internal statistics for metrics calculation
        self._stats = {
            'gets': 0,
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'errors': 0
        }
        self._initialize_redis()

    @classmethod
    async def start(cls, settings=None):
        """Async factory method for lifespan-managed initialization."""
        instance = cls()
        # Test connection health
        if await instance.health_check():
            log.info("RedisCacheService initialized and connection verified")
        else:
            log.warning("RedisCacheService initialized but Redis connection unavailable")

        # Initialize cache TTL metrics
        cache_ttl_seconds.labels(cache_type='embedding').set(instance._ttl_embeddings)
        cache_ttl_seconds.labels(cache_type='splade').set(instance._ttl_splade_vectors)
        cache_ttl_seconds.labels(cache_type='query').set(instance._ttl_query_results)

        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        if self._redis_client:
            await self._redis_client.aclose()
            log.info("Redis connection closed")
            self._redis_available = False

    async def update_metrics(self):
        """
        Update Prometheus metrics with current cache statistics.
        Should be called periodically (e.g., every 60 seconds).
        """
        if not self._redis_available or not self._redis_client:
            return

        try:
            # Calculate hit rates from internal counters
            total_gets = self._stats['gets']
            total_hits = self._stats['hits']

            if total_gets > 0:
                overall_hit_rate = (total_hits / total_gets) * 100
                update_cache_hit_rate('overall', overall_hit_rate)

            # Update cache size estimate (if Redis info is available)
            try:
                info = await self._redis_client.info('memory')
                used_memory = info.get('used_memory', 0)
                cache_size_bytes.labels(cache_type='overall').set(used_memory)
            except Exception as e:
                log.debug(f"Could not get Redis memory info: {e}")

        except Exception as e:
            log.warning(f"Failed to update cache metrics: {e}")

    def _initialize_redis(self):
        """Initialize Redis connection with configuration."""
        try:
            # Load Redis config from Pydantic Settings
            settings = get_settings()
            self._config = {
                'enabled': settings.redis_enabled,
                'url': settings.redis_url,
                'ttl_embeddings': EMBEDDING_CACHE_TTL,
                'ttl_splade_vectors': EMBEDDING_CACHE_TTL,
                'ttl_query_results': LLM_QUERY_CACHE_TTL,
                'key_prefix': 'ontologic'
            }

            # Check if caching is enabled
            if not self._config.get('enabled', True):
                log.info("Redis caching is disabled in configuration")
                self._redis_available = False
                return

            # Parse Redis URL from settings (e.g., "redis://localhost:6379" or "redis://user:pass@host:port/db")
            redis_url = self._config.get('url', 'redis://localhost:6379')
            
            # Parse URL components - support both redis:// and redis+ssl:// schemes
            import urllib.parse
            parsed_url = urllib.parse.urlparse(redis_url)
            
            host = parsed_url.hostname or 'localhost'
            port = parsed_url.port or 6379
            db = int(parsed_url.path.lstrip('/')) if parsed_url.path and parsed_url.path != '/' else 0
            password = parsed_url.password
            
            # Environment variable overrides still supported
            host = os.getenv('REDIS_HOST', host)
            port = int(os.getenv('REDIS_PORT', str(port)))
            db = int(os.getenv('REDIS_DB', str(db)))
            if os.getenv('REDIS_PASSWORD'):
                password = os.getenv('REDIS_PASSWORD')

            # Connection pool settings - use defaults since not in Pydantic Settings yet
            max_connections = 10
            socket_timeout = 5
            socket_connect_timeout = 5

            # Log configuration (but not password!)
            log.info(
                f"Redis config: host={host}, port={port}, db={db}, "
                f"password={'set' if password else 'not set'}"
            )

            # Create async Redis client
            self._redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=False,  # We handle encoding/decoding
                max_connections=max_connections,
                socket_timeout=socket_timeout,
                socket_connect_timeout=socket_connect_timeout,
            )

            # Store TTL settings
            self._ttl_embeddings = self._config.get('ttl_embeddings', 86400)
            self._ttl_splade_vectors = self._config.get('ttl_splade_vectors', 86400)
            self._ttl_query_results = self._config.get('ttl_query_results', 3600)

            # Validate and set key prefix
            self._key_prefix = self._config.get('key_prefix', 'ontologic')
            if not self._key_prefix or len(self._key_prefix) < 3:
                log.warning(f"Key prefix '{self._key_prefix}' is too short, using 'ontologic-default'")
                self._key_prefix = 'ontologic-default'

            log.info(f"Redis cache using key prefix: '{self._key_prefix}'")

            self._redis_available = True
            log.info(f"Redis cache service initialized: {host}:{port}/{db}")

        except Exception as e:
            log.warning(f"Redis initialization failed: {e} - running without cache")
            self._redis_available = False
            self._redis_client = None

    def _make_cache_key(self, prefix: str, *args, **kwargs) -> str:
        """
        Generate deterministic cache key from arguments.

        Args:
            prefix: Key prefix for categorization
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash

        Returns:
            Cache key in format: {key_prefix}:{prefix}:{sha256_hash}

            Note: Uses SHA-256 for collision resistance. Hash is 64 hexadecimal characters.
        """
        try:
            # Convert arguments to JSON-serializable format
            key_data = {
                'args': self._serialize_key_args(args),
                'kwargs': self._serialize_key_args(kwargs)
            }

            # Create deterministic JSON string
            json_str = json.dumps(key_data, sort_keys=True)

            # SECURITY: Use SHA-256 instead of MD5 to prevent collision attacks.
            # While cache keys are not cryptographic, collision resistance prevents
            # cache poisoning where attackers craft inputs with identical hashes.
            # Generate SHA-256 hash for collision resistance
            hash_value = hashlib.sha256(json_str.encode()).hexdigest()

            return f"{self._key_prefix}:{prefix}:{hash_value}"

        except Exception as e:
            log.warning(f"Failed to generate cache key: {e}")
            # Fallback to simple string concatenation
            return f"{self._key_prefix}:{prefix}:{hash(str(args) + str(kwargs))}"

    def make_constant_cache_key(self, constant_key: str) -> str:
        """
        Generate cache key for constant-based keys (no dynamic arguments).

        This is the public API for simple cache keys based on constants.
        Use this when your cache key doesn't depend on function arguments.

        Args:
            constant_key: Constant key name (e.g., from app.core.constants)

        Returns:
            Full cache key with prefix and hash

        Example:
            from app.core.constants import CACHE_KEY_PHILOSOPHER_COLLECTIONS
            cache_key = cache_service.make_constant_cache_key(CACHE_KEY_PHILOSOPHER_COLLECTIONS)

        Note:
            This is a convenience wrapper around _make_cache_key() for constant keys.
            It generates the same deterministic key as _make_cache_key(constant_key)
            but provides a clearer API for external code.
        """
        return self._make_cache_key(constant_key)

    def _serialize_key_args(self, obj):
        """Convert objects to JSON-serializable format for key generation.

        Handles Pydantic models, None values, collections, and complex objects
        with deterministic serialization to ensure consistent cache keys.

        Args:
            obj: Object to serialize for cache key generation

        Returns:
            JSON-serializable representation of the object
        """
        # Handle None explicitly
        if obj is None:
            return None

        # Handle primitives
        if isinstance(obj, (str, int, float, bool)):
            return obj

        # Handle dictionaries with sorted keys for deterministic ordering
        if isinstance(obj, dict):
            return {k: self._serialize_key_args(v) for k, v in sorted(obj.items())}

        # Handle lists and tuples
        if isinstance(obj, (list, tuple)):
            return [self._serialize_key_args(item) for item in obj]

        # Handle Pydantic v2 models (model_dump method)
        if hasattr(obj, 'model_dump') and callable(getattr(obj, 'model_dump')):
            return self._serialize_key_args(obj.model_dump())

        # Handle Pydantic v1 models (dict method)
        if hasattr(obj, 'dict') and callable(getattr(obj, 'dict')):
            return self._serialize_key_args(obj.dict())

        # For unknown complex objects, use string representation with logging
        # This helps debug cache key issues in production
        log.debug(
            f"Cache key serialization: using str() for {type(obj).__module__}.{type(obj).__name__}"
        )
        return str(obj)

    def _serialize(self, value: Any) -> bytes:
        """
        Serialize value for Redis storage using secure JSON-only encoding.

        Uses SafeJSONEncoder to handle Pydantic models, numpy arrays, datetime objects,
        and other common types without the security risks of pickle deserialization.

        Args:
            value: Value to serialize (must be JSON-serializable or supported by SafeJSONEncoder)

        Returns:
            Serialized bytes with 'json:' prefix, or None if serialization fails

        Raises:
            No exceptions raised; returns None on serialization failure with warning log
        """
        try:
            encoded_value = self._encode_for_cache(value)
            json_data = json.dumps(encoded_value, cls=SafeJSONEncoder)
            # Retain the 'json:' prefix for backward compatibility with existing entries
            return b"json:" + json_data.encode("utf-8")
        except Exception as e:
            log.warning(
                f"Failed to serialize value of type {type(value).__name__}: {e}. "
                "Ensure the object is JSON-serializable or supported by SafeJSONEncoder."
            )
            return None

    def _deserialize(self, data: bytes) -> Any:
        """
        Deserialize value from Redis storage (JSON format only).

        Args:
            data: Serialized bytes with 'json:' prefix

        Returns:
            Deserialized value or None on failure

        Note:
            Legacy pickle-serialized data is no longer supported for security reasons.
            Such data will be treated as a cache miss.
        """
        try:
            if data.startswith(b"json:"):
                json_str = data[5:].decode("utf-8")
                decoded_json = json.loads(json_str)
                return self._decode_from_cache(decoded_json)
            if data.startswith(b"pickle:"):
                # SECURITY FIX: Pickle deserialization removed to prevent Remote Code Execution
                log.warning(
                    "Encountered legacy pickle-serialized cache data. Ignoring for security "
                    "reasons. This data will be re-cached in JSON format on next access."
                )
                return None

            log.warning("Unknown serialization format in cache data (missing 'json:' prefix)")
            return None
        except Exception as e:
            log.warning(f"Failed to deserialize cached value: {e}")
            return None

    def _encode_for_cache(self, value: Any) -> Any:
        """Enrich values with metadata needed to rebuild complex objects like Pydantic models."""
        if isinstance(value, BaseModel):
            model_class = value.__class__
            return {
                "__cached_type__": "pydantic_model",
                "module": model_class.__module__,
                "qualname": model_class.__qualname__,
                "data": value.model_dump(),
            }

        if isinstance(value, dict):
            return {k: self._encode_for_cache(v) for k, v in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [self._encode_for_cache(item) for item in value]

        return value

    def _decode_from_cache(self, value: Any) -> Any:
        """Rebuild complex objects from cached metadata when possible."""
        if isinstance(value, dict):
            cached_type = value.get("__cached_type__")
            if cached_type == "pydantic_model":
                model_instance = self._rebuild_pydantic_model(value)
                if model_instance is not None:
                    return model_instance

            return {k: self._decode_from_cache(v) for k, v in value.items()}

        if isinstance(value, list):
            return [self._decode_from_cache(item) for item in value]

        return value

    def _rebuild_pydantic_model(self, payload: Dict[str, Any]) -> Optional[BaseModel]:
        """Attempt to reconstruct a Pydantic model using stored metadata."""
        module_name = payload.get("module")
        qualname = payload.get("qualname")
        data = payload.get("data")

        if not module_name or not qualname:
            log.warning("Missing module or qualname metadata for cached Pydantic model")
            return None

        try:
            module = import_module(module_name)
            model_class: Any = module
            for attr in qualname.split("."):
                model_class = getattr(model_class, attr)

            if not isinstance(model_class, type) or not issubclass(model_class, BaseModel):
                log.warning(
                    "Cached Pydantic metadata resolved to non-BaseModel: %s.%s",
                    module_name,
                    qualname,
                )
                return None

            if hasattr(model_class, "model_validate") and callable(model_class.model_validate):
                return model_class.model_validate(data)

            return model_class(**data)
        except Exception as exc:
            log.warning(
                "Failed to rebuild cached Pydantic model %s.%s: %s",
                module_name,
                qualname,
                exc,
            )
            return None

    @with_retry(max_retries=2, retryable_exceptions=(ConnectionError,))
    @trace_async_operation("cache.get", {"operation": "cache_read"})
    async def get(self, key: str, cache_type: str = 'unknown') -> Optional[Any]:
        """
        Get value from cache with metrics tracking, timeout and retry protection.

        Args:
            key: Cache key
            cache_type: Explicit cache type for metrics (embedding, splade, query).
                       If 'unknown', will attempt to infer from key format.

        Returns:
            Cached value or None if not found/error
        """
        if not self._redis_available or not self._redis_client:
            return None

        # Calculate per-attempt timeout (total 5s / 3 attempts = ~1.66s per attempt)
        total_timeout = 5
        max_attempts, per_attempt_timeout = calculate_per_attempt_timeout(
            total_timeout, max_retries=2
        )

        # If cache_type not provided, attempt to infer from key format
        # This is a fallback for backward compatibility
        if cache_type == 'unknown':
            if ':embedding:' in key:
                cache_type = 'embedding'
            elif ':splade:' in key:
                cache_type = 'splade'
            elif ':query:' in key:
                cache_type = 'query'

        set_span_attributes({
            "cache.operation": "get",
            "cache.type": cache_type,
            "cache.key_prefix": key[:20],  # First 20 chars for privacy
            "cache.timeout_total": total_timeout,
            "cache.timeout_per_attempt": per_attempt_timeout
        })

        try:
            self._stats['gets'] += 1
            data = await asyncio.wait_for(
                self._redis_client.get(key),
                timeout=per_attempt_timeout
            )
            if data is None:
                with self._stats_lock:
                    self._misses += 1
                    self._stats['misses'] += 1
                # Track cache miss in Prometheus
                cache_operations_total.labels(
                    operation='get',
                    cache_type=cache_type,
                    status='miss'
                ).inc()
                add_span_event("cache.miss", {"cache_type": cache_type})
                return None

            value = self._deserialize(data)
            if value is not None:
                with self._stats_lock:
                    self._hits += 1
                    self._stats['hits'] += 1
                # Track cache hit in Prometheus
                cache_operations_total.labels(
                    operation='get',
                    cache_type=cache_type,
                    status='hit'
                ).inc()
                add_span_event("cache.hit", {"cache_type": cache_type})
                # Log cache hit with key prefix only (not full hash for security)
                key_prefix = ':'.join(key.split(':')[:2])
                log.debug(f"Cache hit: {key_prefix}:*")
            return value

        except asyncio.TimeoutError:
            with self._stats_lock:
                self._errors += 1
                self._stats['errors'] += 1
            # Track cache timeout in Prometheus
            cache_operations_total.labels(
                operation='get',
                cache_type=cache_type,
                status='timeout'
            ).inc()
            log.warning(
                f"Cache get timed out after {per_attempt_timeout}s (total: {total_timeout}s) for key: {key[:50]}..."
            )
            return None

        except Exception as e:
            with self._stats_lock:
                self._errors += 1
                self._stats['errors'] += 1
            # Track cache error in Prometheus
            cache_operations_total.labels(
                operation='get',
                cache_type=cache_type,
                status='error'
            ).inc()
            log.warning(f"Cache get error for {key}: {e}")
            return None

    @with_retry(max_retries=2, retryable_exceptions=(ConnectionError,))
    @trace_async_operation("cache.set", {"operation": "cache_write"})
    async def set(self, key: str, value: Any, ttl: int, cache_type: str = 'unknown') -> bool:
        """
        Set value in cache with TTL and metrics tracking, timeout and retry protection.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds
            cache_type: Explicit cache type for metrics (embedding, splade, query).
                       If 'unknown', will attempt to infer from key format.

        Returns:
            True on success, False on failure
        """
        if not self._redis_available or not self._redis_client:
            return False

        # Calculate per-attempt timeout (total 5s / 3 attempts = ~1.66s per attempt)
        total_timeout = 5
        max_attempts, per_attempt_timeout = calculate_per_attempt_timeout(
            total_timeout, max_retries=2
        )

        # If cache_type not provided, attempt to infer from key format
        # This is a fallback for backward compatibility
        if cache_type == 'unknown':
            if ':embedding:' in key:
                cache_type = 'embedding'
            elif ':splade:' in key:
                cache_type = 'splade'
            elif ':query:' in key:
                cache_type = 'query'

        # Validate TTL
        if not isinstance(ttl, int) or ttl <= 0:
            log.warning(f"Invalid TTL {ttl}, must be positive integer. Skipping cache set.")
            return False

        # Reasonable upper limit (30 days)
        if ttl > 2592000:
            log.warning(f"TTL {ttl}s exceeds 30 days, clamping to 2592000s")
            ttl = 2592000

        set_span_attributes({
            "cache.operation": "set",
            "cache.type": cache_type,
            "cache.key_prefix": key[:20],
            "cache.ttl": ttl,
            "cache.timeout_total": total_timeout,
            "cache.timeout_per_attempt": per_attempt_timeout
        })

        try:
            self._stats['sets'] += 1
            serialized = self._serialize(value)
            if serialized is None:
                log.warning(
                    f"Failed to serialize value of type {type(value).__name__} for caching. "
                    "Value will not be cached."
                )
                return False

            await asyncio.wait_for(
                self._redis_client.setex(key, ttl, serialized),
                timeout=per_attempt_timeout
            )

            # Track cache set in Prometheus
            cache_operations_total.labels(
                operation='set',
                cache_type=cache_type,
                status='success'
            ).inc()

            add_span_event("cache.set_success", {
                "cache_type": cache_type,
                "ttl": ttl
            })

            # Log cache set with key prefix only
            key_prefix = ':'.join(key.split(':')[:2])
            log.debug(f"Cache set: {key_prefix}:* (TTL={ttl}s)")
            return True

        except asyncio.TimeoutError:
            with self._stats_lock:
                self._errors += 1
                self._stats['errors'] += 1
            # Track cache timeout in Prometheus
            cache_operations_total.labels(
                operation='set',
                cache_type=cache_type,
                status='timeout'
            ).inc()
            log.warning(
                f"Cache set timed out after {per_attempt_timeout}s (total: {total_timeout}s) for key: {key[:50]}..."
            )
            return False

        except Exception as e:
            with self._stats_lock:
                self._errors += 1
                self._stats['errors'] += 1
            # Track cache error in Prometheus
            cache_operations_total.labels(
                operation='set',
                cache_type=cache_type,
                status='error'
            ).inc()
            log.warning(f"Cache set error for {key}: {e}")
            return False

    def cached(self, prefix: str, ttl: int):
        """
        Decorator factory for caching async function results.

        Args:
            prefix: Cache key prefix
            ttl: Time-to-live in seconds

        Returns:
            Decorator function
        """
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Generate cache key from function arguments
                cache_key = self._make_cache_key(prefix, *args, **kwargs)

                # Try to get from cache with explicit cache_type for accurate metrics
                cached_value = await self.get(cache_key, cache_type=prefix)
                if cached_value is not None:
                    return cached_value

                # Cache miss - call original function
                try:
                    result = await func(*args, **kwargs)

                    # Store in cache (don't fail if caching fails) with explicit cache_type
                    await self.set(cache_key, result, ttl, cache_type=prefix)

                    return result

                except Exception as e:
                    # If function fails, don't cache and re-raise
                    log.error(f"Function {func.__name__} failed: {e}")
                    raise

            return wrapper
        return decorator

    def cache_embedding(self, ttl: Optional[int] = None):
        """Decorator for caching embeddings (24h default TTL)."""
        ttl = ttl or self._ttl_embeddings
        return self.cached('embedding', ttl)

    def cache_splade_vector(self, ttl: Optional[int] = None):
        """Decorator for caching SPLADE vectors (24h default TTL)."""
        ttl = ttl or self._ttl_splade_vectors
        return self.cached('splade', ttl)

    def cache_query_results(self, ttl: Optional[int] = None):
        """Decorator for caching query results (1h default TTL)."""
        ttl = ttl or self._ttl_query_results
        return self.cached('query', ttl)

    async def health_check(self) -> bool:
        """
        Test Redis connectivity with actual network call.

        Returns:
            True if Redis is reachable, False otherwise
        """
        if not self._redis_available or not self._redis_client:
            return False
        try:
            await self._redis_client.ping()
            return True
        except Exception as e:
            log.warning(f"Redis health check failed: {e}")
            self._redis_available = False
            return False

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.

        Returns:
            Dictionary with cache metrics
        """
        with self._stats_lock:
            hits = self._hits
            misses = self._misses
            errors = self._errors
        
        total_requests = hits + misses
        hit_rate = (hits / total_requests * 100) if total_requests > 0 else 0

        return {
            'enabled': self._config.get('enabled', True),
            'available': self._redis_available,
            'hits': hits,
            'misses': misses,
            'hit_rate': round(hit_rate, 2),
            'errors': errors,
        }


    async def close(self):
        """Close Redis connection."""
        if self._redis_client:
            try:
                await self._redis_client.close()
                log.info("Redis cache connection closed")
            except Exception as e:
                log.warning(f"Error closing Redis connection: {e}")
            finally:
                self._redis_available = False
                self._redis_client = None

    async def clear_cache(self, pattern: Optional[str] = None):
        """
        Clear cache entries.

        Args:
            pattern: Optional key pattern to match (None = flush all)
        """
        if not self._redis_available or not self._redis_client:
            log.warning("Cannot clear cache: Redis not available")
            return

        try:
            if pattern:
                # Delete matching keys
                keys = []
                async for key in self._redis_client.scan_iter(match=pattern):
                    keys.append(key)

                if keys:
                    await self._redis_client.delete(*keys)
                    log.info(f"Cleared {len(keys)} cache entries matching: {pattern}")
            else:
                # Flush entire database
                await self._redis_client.flushdb()
                log.info("Cleared all cache entries")

        except Exception as e:
            with self._stats_lock:
                self._errors += 1
                self._stats['errors'] += 1
            log.warning(f"Failed to clear cache: {e}")
