"""
Cache warming service for preloading frequently accessed data.

Improves application performance by warming the cache during startup
with data that is frequently accessed by users.
"""

from typing import List, Dict, Any, Optional
import time
from app.core.logger import log
from app.core.metrics import (
    track_cache_warming,
    cache_warming_operations_total
)
from app.core.constants import (
    CACHE_KEY_PHILOSOPHER_COLLECTIONS,
    PHILOSOPHER_COLLECTIONS_CACHE_TTL
)
from app.core.collection_filters import filter_philosopher_collections
from app.core.exceptions import (
    CacheOperationError,
    EmbeddingWarmupError,
    DependencyUnavailableError
)


class CacheWarmingService:
    """
    Service for warming cache with frequently accessed data during startup.

    Warming targets:
    - Philosopher collection names (used in /get_philosophers)
    - Common query patterns (if identified through analytics)
    """

    def __init__(
        self,
        qdrant_manager=None,
        cache_service=None,
        llm_manager=None,
        enabled: bool = True,
        warming_items: str = "collections,embeddings"
    ):
        """
        Initialize cache warming service.

        Args:
            qdrant_manager: QdrantManager instance for collection queries
            cache_service: RedisCacheService for cache operations
            llm_manager: LLMManager instance for generating embeddings
            enabled: Whether cache warming is enabled
            warming_items: Comma-separated list of items to warm (collections, embeddings)
        """
        self.qdrant_manager = qdrant_manager
        self.cache_service = cache_service
        self.llm_manager = llm_manager
        self.enabled = enabled
        self.warming_items = [item.strip() for item in warming_items.split(',')]
        self._warming_stats = {
            "philosopher_collections": {"success": False, "items_warmed": 0, "duration_seconds": 0},
            "common_embeddings": {"success": False, "items_warmed": 0, "duration_seconds": 0},
            "errors": [],
            "total_duration_seconds": 0
        }

    @track_cache_warming(warming_type='overall')
    async def warm_cache(self) -> Dict[str, Any]:
        """
        Execute cache warming strategy.

        Returns:
            Dictionary with warming results and statistics
        """
        if not self.enabled:
            log.info("Cache warming is disabled")
            cache_warming_operations_total.labels(
                warming_type='overall',
                status='skipped'
            ).inc()
            return {"enabled": False, "stats": self._warming_stats}

        start_time = time.time()
        log.info(f"Starting cache warming for items: {', '.join(self.warming_items)}...")

        # Warm philosopher collections list
        if 'collections' in self.warming_items:
            try:
                await self._warm_philosopher_collections()
            except Exception as e:
                # Differentiate between expected and unexpected errors
                error_type = type(e).__name__
                error_msg = str(e)

                # Update stats with error details
                self._warming_stats["philosopher_collections"] = {
                    "success": False,
                    "items_warmed": 0,
                    "duration_seconds": 0
                }
                self._warming_stats["errors"].append(f"collections: {error_type} - {error_msg[:100]}")

                # Expected errors (services unavailable) - INFO level
                if "unavailable" in error_msg.lower() or "not available" in error_msg.lower():
                    log.info(
                        f"Collections warming skipped due to unavailable service: {e}",
                        extra={"error_type": error_type, "warming_type": "collections"}
                    )
                # Unexpected errors (bugs) - WARNING level with full traceback
                else:
                    log.warning(
                        f"Collections warming failed with unexpected error: {e}",
                        exc_info=True,
                        extra={"error_type": error_type, "warming_type": "collections"}
                    )

        # Warm common embeddings
        if 'embeddings' in self.warming_items:
            try:
                await self._warm_common_embeddings()
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)

                # Update stats with error details
                self._warming_stats["common_embeddings"] = {
                    "success": False,
                    "items_warmed": 0,
                    "duration_seconds": 0
                }
                self._warming_stats["errors"].append(f"embeddings: {error_type} - {error_msg[:100]}")

                # Expected errors (services unavailable) - INFO level
                if "unavailable" in error_msg.lower() or "not available" in error_msg.lower():
                    log.info(
                        f"Embeddings warming skipped due to unavailable service: {e}",
                        extra={"error_type": error_type, "warming_type": "embeddings"}
                    )
                # Unexpected errors (bugs) - WARNING level with full traceback
                else:
                    log.warning(
                        f"Embeddings warming failed with unexpected error: {e}",
                        exc_info=True,
                        extra={"error_type": error_type, "warming_type": "embeddings"}
                    )

        total_duration = time.time() - start_time
        self._warming_stats["total_duration_seconds"] = round(total_duration, 3)

        # Log summary with appropriate level
        if self._warming_stats["errors"]:
            log.warning(
                f"Cache warming completed with errors in {total_duration:.2f}s. "
                f"Errors: {self._warming_stats['errors']}"
            )
        else:
            log.info(f"Cache warming completed successfully in {total_duration:.2f}s")

        return {"enabled": True, "stats": self._warming_stats}

    @track_cache_warming(warming_type='collections')
    async def _warm_philosopher_collections(self) -> int:
        """
        Warm cache with philosopher collection names.

        This is one of the most frequently accessed queries in the application,
        used by /get_philosophers endpoint and various UI components.

        The method:
        1. Fetches collection names from Qdrant
        2. Filters to philosopher collections
        3. Stores the list in Redis cache with appropriate TTL

        Returns:
            int: Number of items warmed (consumed by @track_cache_warming decorator for metrics)
        """
        if not self.qdrant_manager:
            log.warning("Cache warming skipped: QdrantManager not available")
            self._warming_stats["errors"].append("qdrant_manager_unavailable")
            cache_warming_operations_total.labels(
                warming_type='collections',
                status='skipped'
            ).inc()
            return 0

        if not self.cache_service:
            log.warning("Cache warming skipped: CacheService not available")
            self._warming_stats["errors"].append("cache_service_unavailable")
            cache_warming_operations_total.labels(
                warming_type='collections',
                status='skipped'
            ).inc()
            return 0

        start_time = time.time()

        log.info("Warming philosopher collections cache...")

        try:
            # Fetch collections from Qdrant
            collections = await self.qdrant_manager.get_collections()

            # Extract collection names
            collection_names = [c.name for c in collections.collections]

            # Filter to philosopher collections using shared utility
            # CRITICAL: This MUST use the same filtering logic as /get_philosophers endpoint
            # to ensure cached data matches what the endpoint produces on cache miss
            available_philosophers = filter_philosopher_collections(collection_names)

            # ACTUAL CACHING: Store the philosopher list in Redis
            # Use standard cache key constant to ensure consistency with endpoint
            cache_key = self.cache_service.make_constant_cache_key(CACHE_KEY_PHILOSOPHER_COLLECTIONS)
            cache_ttl = PHILOSOPHER_COLLECTIONS_CACHE_TTL

            success = await self.cache_service.set(
                cache_key,
                available_philosophers,
                cache_ttl,
                cache_type='query'  # Use 'query' cache type for metrics
            )

            if not success:
                raise CacheOperationError("Failed to store collections in cache")

            # Update stats on success
            duration = time.time() - start_time
            items_count = len(available_philosophers)
            self._warming_stats["philosopher_collections"] = {
                "success": True,
                "items_warmed": items_count,
                "duration_seconds": round(duration, 3)
            }

            log.info(
                f"Successfully warmed philosopher collections cache: "
                f"{items_count} philosophers cached in {duration:.2f}s"
            )

            # Return count for decorator to track via items_count_fn
            return items_count

        except Exception as exc:
            # Handle Qdrant or cache errors gracefully
            log.error(f"Failed to warm philosopher collections cache: {exc}", exc_info=True)
            self._warming_stats["errors"].append(f"philosopher_collections_error: {exc}")
            self._warming_stats["philosopher_collections"] = {
                "success": False,
                "items_warmed": 0,
                "duration_seconds": 0
            }
            cache_warming_operations_total.labels(
                warming_type='collections',
                status='error'
            ).inc()
            return 0

    @track_cache_warming(warming_type='embeddings')
    async def _warm_common_embeddings(self) -> int:
        """
        Warm cache with embeddings for common philosopher names.

        Pre-generates embeddings for philosopher names that are frequently
        used in queries. This improves response time for the first query
        after application startup.

        The method:
        1. Generates embeddings for each philosopher name
        2. Stores embeddings in Redis cache with appropriate TTL
        3. Tracks success/failure metrics

        Returns:
            int: Number of embeddings warmed (consumed by @track_cache_warming decorator for metrics)
        """
        if not self.llm_manager:
            log.warning("Cache warming skipped: LLMManager not available")
            self._warming_stats["errors"].append("llm_manager_unavailable")
            cache_warming_operations_total.labels(
                warming_type='embeddings',
                status='skipped'
            ).inc()
            return 0

        if not self.cache_service:
            log.warning("Cache warming skipped: CacheService not available")
            self._warming_stats["errors"].append("cache_service_unavailable")
            cache_warming_operations_total.labels(
                warming_type='embeddings',
                status='skipped'
            ).inc()
            return 0

        start_time = time.time()

        # No outer try/except - let decorator handle error tracking
        log.info("Warming common embeddings cache...")

        # Common philosopher names and related terms frequently used in queries
        common_terms = [
            "Aristotle",
            "John Locke",
            "Friedrich Nietzsche",
            "Immanuel Kant",
            "David Hume",
            "ethics",
            "metaphysics",
            "epistemology",
            "political philosophy",
            "virtue ethics"
        ]

        warmed_count = 0

        for term in common_terms:
            try:
                # Generate embedding (this will automatically cache it via LLMManager)
                # The LLMManager.get_embedding() method already has caching logic
                await self.llm_manager.get_embedding(term)
                warmed_count += 1
                log.debug(f"Warmed embedding for: {term}")
            except Exception as e:
                log.warning(f"Failed to warm embedding for '{term}': {e}")
                # Continue with other terms even if one fails

        if warmed_count == 0:
            raise EmbeddingWarmupError("Failed to warm any embeddings")

        # Update stats on success
        duration = time.time() - start_time
        self._warming_stats["common_embeddings"] = {
            "success": True,
            "items_warmed": warmed_count,
            "duration_seconds": round(duration, 3)
        }

        log.info(
            f"Successfully warmed {warmed_count}/{len(common_terms)} embeddings "
            f"in {duration:.2f}s"
        )

        # Return count for decorator to track via items_count_fn
        return warmed_count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache warming statistics.

        Returns:
            Dictionary with warming statistics
        """
        return {
            "enabled": self.enabled,
            "stats": self._warming_stats
        }
