import asyncio
from typing import Any, Dict, List, TYPE_CHECKING
from qdrant_client import AsyncQdrantClient, models
from app.core.models import HybridQueryRequest
from app.core.logger import log
from app.core.exceptions import LLMTimeoutError, LLMUnavailableError
from app.core.cache_helpers import with_cache
from app.core.http_error_guard import with_timeout
from app.core.constants import DEFAULT_QDRANT_TIMEOUT_SECONDS, META_REFEED_LIMIT, LLM_QUERY_CACHE_TTL
from app.core.metrics import (
    track_qdrant_query,
    qdrant_query_duration_seconds,
    qdrant_query_results_total,
    qdrant_query_total,
    qdrant_collection_points
)
from app.core.tracing import trace_async_operation, set_span_attributes, add_span_event
import time

if TYPE_CHECKING:
    from app.services.llm_manager import LLMManager
    from app.services.cache_service import RedisCacheService


# Note: This class is no longer a singleton. Use dependency injection from app.core.dependencies.get_qdrant_manager().
class QdrantManager:

    def __init__(self, llm_manager: 'LLMManager' = None, cache_service: 'RedisCacheService' = None):
        """Initialize Qdrant manager with optional injected LLMManager and cache_service."""
        import os
        from app.config.settings import get_settings

        # Get Qdrant configuration from Pydantic Settings with proper env var support
        settings = get_settings()
        qdrant_url = settings.qdrant_url  # Respects APP_QDRANT_URL env var
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None

        # For backward compatibility, also check QDRANT_API_KEY
        if not api_key:
            api_key = os.environ.get("QDRANT_API_KEY")

        # Default timeout and other settings
        timeout_seconds = DEFAULT_QDRANT_TIMEOUT_SECONDS

        # Create qdrant_config dict for backward compatibility
        qdrant_config = {
            "url": qdrant_url,
            "api_key": api_key,
            "timeout": timeout_seconds,
            "retry_attempts": 3
        }

        # For local Qdrant, use host/port instead of URL
        is_local = "localhost" in qdrant_url or "127.0.0.1" in qdrant_url

        if is_local:
            # Extract port from URL or use default
            import re
            port_match = re.search(r':(\d+)', qdrant_url)
            port = int(port_match.group(1)) if port_match else 6333

            self.qclient = AsyncQdrantClient(
                host="127.0.0.1",
                port=port,
                api_key=None,
                timeout=timeout_seconds,
                prefer_grpc=False
            )
        else:
            self.qclient = AsyncQdrantClient(
                url=qdrant_url,
                port=None,
                api_key=api_key if api_key else None,
                timeout=timeout_seconds
            )

        if llm_manager is not None:
            self.llm_manager = llm_manager
            log.debug("QdrantManager using injected LLMManager")
        else:
            from app.services.llm_manager import LLMManager

            self.llm_manager = LLMManager()
            log.warning("QdrantManager creating own LLMManager - consider using dependency injection")

        self.config = qdrant_config
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(1, int(qdrant_config.get("retry_attempts", 3)))
        self._cache_service = cache_service  # Injected cache service for query result caching

        # Store TTL value locally for safer access (avoid AttributeError if cache_service is None or lacks attributes)
        self._query_ttl = getattr(cache_service, '_ttl_query_results', LLM_QUERY_CACHE_TTL) if cache_service else LLM_QUERY_CACHE_TTL

        if cache_service is not None:
            log.debug("QdrantManager using injected RedisCacheService for query caching")

    @classmethod
    async def start(cls, settings=None, llm_manager=None, cache_service=None):
        """
        Async factory method for lifespan-managed initialization.

        Args:
            settings: Optional settings override
            llm_manager: Optional LLMManager instance for dependency injection
            cache_service: Optional RedisCacheService instance for query result caching

        Returns:
            Initialized QdrantManager instance
        """
        instance = cls(llm_manager=llm_manager, cache_service=cache_service)
        await instance.validate_connection()

        # Initialize collection metrics
        try:
            await instance.update_collection_metrics()
        except Exception as e:
            log.warning(f"Could not initialize Qdrant collection metrics: {e}")

        log.info("QdrantManager initialized and connection validated with Prometheus metrics")
        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        if hasattr(self, 'qclient') and self.qclient:
            await self.qclient.close()
            log.info("QdrantManager connection closed")

    async def execute_with_retries(self, operation, timeout_seconds=None, operation_name="Qdrant operation"):
        """Execute an async operation with retry and timeout handling using centralized timeout decorator."""
        attempts = self.retry_attempts
        last_error = None
        timeout_seconds = timeout_seconds or self.timeout_seconds

        for attempt in range(1, attempts + 1):
            try:
                # Use centralized with_timeout decorator for consistent timeout handling
                @with_timeout(timeout_seconds=timeout_seconds, operation_name=operation_name)
                async def _execute():
                    try:
                        return await operation()
                    except Exception as e:
                        # Convert generic exceptions to LLMUnavailableError for consistency
                        if not isinstance(e, (LLMTimeoutError, LLMUnavailableError, asyncio.TimeoutError)):
                            log.error(f"{operation_name} failed: {e}")
                            raise LLMUnavailableError(f"{operation_name} failed: {str(e)}")
                        raise

                return await _execute()
            except (LLMTimeoutError, LLMUnavailableError) as exc:
                last_error = exc
                if attempt >= attempts:
                    log.error(f"{operation_name} failed after {attempts} attempts")
                    raise
                backoff = min(2 ** (attempt - 1), 8)
                log.warning(
                    f"{operation_name} attempt {attempt} failed ({exc}). Retrying in {backoff}s..."
                )
                await asyncio.sleep(backoff)

        if last_error:
            raise last_error

    @trace_async_operation("qdrant.validate_connection", {"operation": "health_check"})
    async def validate_connection(self):
        """Validate Qdrant connection health."""
        try:
            collections = await self.execute_with_retries(
                lambda: self.qclient.get_collections(),
                timeout_seconds=DEFAULT_QDRANT_TIMEOUT_SECONDS,
                operation_name="Qdrant connection validation"
            )
            log.info(f"Qdrant connection validated successfully. Found {len(collections.collections)} collections.")

            add_span_event("qdrant.connection_validated", {
                "collections_count": len(collections.collections)
            })

            return True
        except Exception as e:
            log.error(f"Qdrant connection validation failed: {e}")
            raise ConnectionError(f"Cannot connect to Qdrant: {e}")

    @trace_async_operation("qdrant.get_collections", {"operation": "list_collections"})
    async def get_collections(self):
        """Retrieve list of Qdrant collections using the underlying client."""
        return await self.qclient.get_collections()

    async def update_collection_metrics(self):
        """
        Update Prometheus metrics with current collection point counts.
        Should be called periodically (e.g., every 60 seconds) or after significant operations.
        """
        try:
            collections = await self.qclient.get_collections()

            for collection in collections.collections:
                try:
                    collection_info = await self.qclient.get_collection(collection.name)
                    point_count = collection_info.points_count if hasattr(collection_info, 'points_count') else 0

                    qdrant_collection_points.labels(
                        collection=collection.name
                    ).set(point_count)

                except Exception as e:
                    log.debug(f"Could not get point count for collection {collection.name}: {e}")

            log.debug(f"Updated Qdrant collection metrics for {len(collections.collections)} collections")

        except Exception as e:
            log.warning(f"Failed to update Qdrant collection metrics: {e}")

    @track_qdrant_query(collection='dynamic', query_type='hybrid')
    @trace_async_operation("qdrant.query_hybrid", {"operation": "hybrid_search"})
    async def query_hybrid(
        self,
        query_text: str,
        collection: str,
        limit: int = 10,
        vector_types: List[str] = None,
        filter: Dict[str, Any] = None,
        payload: List[str] = None,
    ) -> Dict[str, List[models.ScoredPoint]]:
        """
        Query multiple vector types and return combined results with caching, timeout and retry protection.

        NOTE: Timeout and retry logic is handled by execute_with_retries() below.
        Removed @with_retry decorator to avoid duplicated retry/timeout causing multiplicative retries.

        Args:
            query_text: The text to search for
            collection: The collection to search
            limit: Number of results per vector type
            vector_types: List of vector types to query (default: all six)

        Returns:
            Dictionary with vector type as key and results as value
        """
        # Validate input parameters
        if not query_text or not query_text.strip():
            raise ValueError(
                "query_text cannot be empty. Please provide a valid search query."
            )

        if not collection or not collection.strip():
            raise ValueError(
                "collection name cannot be empty. Please specify a valid collection."
            )

        async def _execute_query():
            """Inner function to execute the actual query."""
            log.debug(f"Querying collection '{collection}' with {len(vector_types or [])} vector types")

            # Determine vector types based on collection
            selected_vector_types = vector_types
            if not selected_vector_types:
                if collection != "Meta Collection":
                    selected_vector_types = [
                        "sparse_original",
                        "sparse_summary",
                        "sparse_conjecture",
                        "dense_original",
                        "dense_summary",
                        "dense_conjecture",
                    ]
                else:
                    selected_vector_types = [
                        "sparse_original",
                        "sparse_summary",
                        "dense_original",
                        "dense_summary",
                    ]

            set_span_attributes({
                "qdrant.collection": collection,
                "qdrant.limit": limit,
                "qdrant.query_length": len(query_text),
                "qdrant.vector_types_count": len(selected_vector_types),
                "qdrant.has_filter": filter is not None
            })

            # Build query filter if provided
            query_filter = self.generate_qdrant_must_filter(filter) if filter is not None else None

            # Build requests for each vector type
            requests = []
            for vector_type in selected_vector_types:
                if "sparse" in vector_type:
                    splade_vec = await self.llm_manager.generate_splade_vector(query_text)
                    query = models.SparseVector(indices=splade_vec["indices"], values=splade_vec["values"])
                else:
                    query = await self.llm_manager.generate_dense_vector(query_text)

                requests.append(models.QueryRequest(
                    query=query,
                    using=vector_type,
                    limit=limit,
                    filter=query_filter,
                    with_payload=payload if payload else True
                ))

            # Execute batch query with built-in retry and timeout handling
            batch_results = await self.execute_with_retries(
                lambda: self.qclient.query_batch_points(
                    collection_name=collection,
                    requests=requests
                ),
                timeout_seconds=self.timeout_seconds,
                operation_name=f"Batch query for collection {collection}"
            )

            # Build results dictionary
            results = {}
            for vector_type, batch_result in zip(selected_vector_types, batch_results):
                results[vector_type] = batch_result.points

            # Record query results
            total_results = sum(len(points) for points in results.values())
            add_span_event("qdrant.results_retrieved", {
                "total_results": total_results,
                "vector_types": ",".join(selected_vector_types)
            })

            return results

        # Use with_cache helper for consistent caching pattern
        # Cache key must include ALL parameters that affect the result
        return await with_cache(
            self._cache_service,
            'query',
            _execute_query,
            self._query_ttl,
            query_text,      # Primary input
            collection,      # Affects results
            limit,           # Affects results
            vector_types,    # Affects results
            filter,          # Affects results
            payload          # Affects results
        )

    def generate_qdrant_must_filter(self, conditions: Dict[str, Any]) -> models.Filter:
        filter_conditions = []
        for key, value in conditions.items():
            if isinstance(value, list):
                filter_conditions.append(
                    models.FieldCondition(key=key, match=models.MatchAny(any=value))
                )
            else:
                filter_conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        return models.Filter(must=filter_conditions)

    def generate_qdrant_filter(self, filter_config: Dict[str, Any]) -> models.Filter:
        """
        Generate Qdrant filter from flexible configuration.
        
        Args:
            filter_config: Can be:
                - Simple dict: {"field": "value"} (defaults to must)
                - Complex dict: {"must": {...}, "should": {...}, "must_not": {...}}
        """
        # If no boolean operators, assume it's a simple must filter
        if not any(key in filter_config for key in ["must", "should", "must_not"]):
            return models.Filter(must=self._build_conditions(filter_config))
        
        # Build complex filter
        filter_kwargs = {}
        for filter_type in ["must", "should", "must_not"]:
            if filter_type in filter_config:
                filter_kwargs[filter_type] = self._build_conditions(filter_config[filter_type])
        
        return models.Filter(**filter_kwargs)

    def _build_conditions(self, conditions: Dict[str, Any]) -> List[models.FieldCondition]:
        """Helper to build condition list"""
        condition_list = []
        for key, value in conditions.items():
            if isinstance(value, list):
                condition_list.append(
                    models.FieldCondition(key=key, match=models.MatchAny(any=value))
                )
            else:
                condition_list.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        return condition_list

    async def close(self):
        """Close Qdrant client resources. Instance can be garbage collected after this."""
        try:
            if hasattr(self, "qclient") and self.qclient is not None:
                await self.qclient.close()
                log.info("Qdrant client connection closed")
        except Exception as exc:
            log.warning(f"Failed to close Qdrant client cleanly: {exc}")

    def get_tokens_and_weights(self, sparse_embedding):
        token_weight_dict = {}
        for i in range(len(sparse_embedding.indices)):
            token = self.llm_manager.splade_tokenizer.decode([sparse_embedding.indices[i]])
            weight = sparse_embedding.values[i]
            token_weight_dict[token] = weight

        # Sort the dictionary by weights
        token_weight_dict = dict(
            sorted(token_weight_dict.items(), key=lambda item: item[1], reverse=True)
        )
        return token_weight_dict
    
    #TODO look itno hybrid search and full text filtering
    #TODO determine if this is preferential to metanodes or not
    def select_top_nodes(self, collection_name, nodes, meta_nodes=None, limit=3):
        log.info(f"Selecting top nodes from collection: {collection_name} with limit: {limit}")
        all_points = []
        
        for item_list in nodes.values():
            for item in item_list:
                item.payload["collection_name"] = collection_name
            all_points.extend(item_list)

        top_nodes = sorted(all_points, key=lambda x: x.score, reverse=True)[:limit]
        
        
        all_meta_points = []

        if meta_nodes:
            for item_list in meta_nodes.values():
                all_meta_points.extend(item_list)
                for item in item_list:
                    item.payload["collection_name"] = "Meta Collection"

            top_meta_nodes = sorted(all_meta_points, key=lambda x: x.score, reverse=True)[:limit]
            top_nodes = top_nodes + top_meta_nodes

        return top_nodes

    def analyze_sparse_matches(self, query_results, vector_type="sparse_original"):
        for i, point in enumerate(query_results):
            if point.vector and vector_type in point.vector:
                sparse_vec = point.vector[vector_type]
                tokens = self.get_tokens_and_weights(sparse_vec)
                log.debug(f"Result {i+1} - Key terms: {list(tokens.keys())[:10]}")

    async def gather_points_and_sort(self, request: HybridQueryRequest, raw_mode: bool = False, refeed: bool = True, limit: int = 3):
        # Validate request query string
        if not request.query_str or not request.query_str.strip():
            raise ValueError(
                "Request query_str cannot be empty. Please provide a valid search query."
            )
        
        top_meta_text_query_str = ""
        meta_nodes = None
        if refeed and request.collection != "Meta Collection":
            try:
                log.info("Fetching meta nodes to refeed into subcollection query...")
                meta_nodes = await self.query_hybrid(
                    request.query_str,
                    "Meta Collection",
                    payload=["text", "summary", "conjecture"],
                    filter={"philosopher": request.collection},
                    vector_types=["sparse_original", "sparse_summary", "dense_original", "dense_summary"],
                    limit=META_REFEED_LIMIT,
                )

                if meta_nodes:
                    top_meta_nodes = []
                    for item_list in meta_nodes.values():
                        top_meta_nodes.extend(item_list)

                    top_meta_nodes = sorted(top_meta_nodes, key=lambda x: x.score, reverse=True)[:3]

                    if top_meta_nodes:
                        top_meta_text_query_str = (
                            "\n".join([node.payload["text"] for node in top_meta_nodes])
                            + f"\n\n{request.query_str}"
                        )
            except Exception as e:
                log.warning(f"Meta refeed failed, falling back to direct query: {e}")
                # Continue with original query - graceful degradation
                meta_nodes = None

        # Determine final query string with validation
        if refeed and meta_nodes and top_meta_text_query_str.strip():
            final_query_str = top_meta_text_query_str.strip()
            log.info(f"Querying collection: {request.collection} with refeed query (length: {len(final_query_str)})")
        else:
            final_query_str = request.query_str.strip()
            if refeed and not meta_nodes:
                log.info(f"Querying collection: {request.collection} with original query (meta refeed unavailable)")
            else:
                log.info(f"Querying collection: {request.collection} with original query")

        # Validate final query string before proceeding
        if not final_query_str:
            raise ValueError(
                "Query string cannot be empty. Please provide a valid search query in the request."
            )

        nodes = await self.query_hybrid(
            final_query_str,
            request.collection, #"Combined Collection",
            vector_types=request.vector_types,
            # filter={"node_hierarchy": "Baby Bear"},
            filter=request.filter,
            payload=request.payload,
        )
        if raw_mode:
            return {f"{request.collection}": nodes, "Meta Collection": meta_nodes} if refeed else {f"{request.collection}": nodes}
        
        return self.select_top_nodes(request.collection, nodes, meta_nodes if refeed else None, limit=limit)

    def rrf_fuse(self, result_lists: list, k: int = 60) -> list:
        """
        Apply Reciprocal Rank Fusion (RRF) to combine multiple ranked result lists.

        RRF formula: score = sum(1/(k + rank)) for each list where item appears

        Args:
            result_lists: List of result lists, each containing scored items
            k: RRF parameter (default 60, as commonly used in literature)

        Returns:
            List of items sorted by RRF score in descending order
        """
        if not result_lists:
            return []

        # Dictionary to accumulate RRF scores for each item
        rrf_scores = {}

        for result_list in result_lists:
            for rank, item in enumerate(result_list, 1):
                # Use item ID as the key for fusion
                item_id = getattr(item, 'id', str(item))

                # Calculate RRF score: 1/(k + rank)
                rrf_score = 1.0 / (k + rank)

                if item_id in rrf_scores:
                    rrf_scores[item_id]['score'] += rrf_score
                else:
                    rrf_scores[item_id] = {
                        'item': item,
                        'score': rrf_score
                    }

        # Sort by RRF score descending
        fused_results = sorted(
            rrf_scores.values(),
            key=lambda x: x['score'],
            reverse=True
        )

        # Return just the items, not the score wrappers
        return [result['item'] for result in fused_results]

    @track_qdrant_query(collection='dynamic', query_type='dense')
    async def query_with_vectors(
        self,
        query_text: str,
        collection: str,
        vector_types: list = None,
        include_vectors: bool = False,
        **kwargs
    ):
        """
        Query hybrid vectors with option to include vector data in response.

        Args:
            query_text: Search query
            collection: Collection name
            vector_types: List of vector types to query
            include_vectors: Whether to include vector data in response
            **kwargs: Additional query parameters

        Returns:
            Query results with optional vector inclusion
        """
        # Use existing query_hybrid method
        results = await self.query_hybrid(
            query_text=query_text,
            collection=collection,
            vector_types=vector_types,
            **kwargs
        )

        if not include_vectors:
            return results

        # Include vector data in results
        enhanced_results = {}
        for vector_type, points in results.items():
            enhanced_points = []
            for point in points:
                # Convert to dict and ensure vectors are included
                point_dict = {
                    'id': point.id,
                    'score': point.score,
                    'payload': point.payload,
                    'vector_type': vector_type
                }

                # Include vector data if available
                if hasattr(point, 'vector') and point.vector:
                    point_dict['vectors'] = point.vector

                enhanced_points.append(point_dict)

            enhanced_results[vector_type] = enhanced_points

        return enhanced_results

    def deduplicate_results(self, results: list, key_field: str = 'id') -> list:
        """
        Remove duplicate results based on a key field.

        Args:
            results: List of result items
            key_field: Field to use for deduplication

        Returns:
            Deduplicated list maintaining order of first occurrence
        """
        seen = set()
        deduplicated = []

        for item in results:
            # Get the key value for deduplication
            if hasattr(item, key_field):
                key_value = getattr(item, key_field)
            elif isinstance(item, dict) and key_field in item:
                key_value = item[key_field]
            else:
                # If key field not found, use string representation
                key_value = str(item)

            if key_value not in seen:
                seen.add(key_value)
                deduplicated.append(item)

        return deduplicated

    @trace_async_operation("qdrant.multi_query_fusion", {"operation": "fusion_search"})
    async def multi_query_fusion(
        self,
        queries: list,
        collection: str,
        fusion_method: str = "rrf",
        rrf_k: int = 60,
        limit: int = 10,
        **query_kwargs
    ):
        """
        Execute multiple queries and fuse results using specified method.

        Args:
            queries: List of query strings
            collection: Collection to query
            fusion_method: Method for fusing results ("rrf" or "score_avg")
            rrf_k: RRF k parameter
            limit: Final result limit
            **query_kwargs: Additional query parameters

        Returns:
            Fused results from all queries
        """
        if not queries:
            return []

        set_span_attributes({
            "qdrant.collection": collection,
            "qdrant.queries_count": len(queries),
            "qdrant.fusion_method": fusion_method,
            "qdrant.rrf_k": rrf_k,
            "qdrant.limit": limit
        })

        # Execute all queries
        all_results = []
        for query in queries:
            try:
                results = await self.query_hybrid(
                    query_text=query,
                    collection=collection,
                    limit=limit * 2,  # Get more results for better fusion
                    **query_kwargs
                )

                # Flatten results from all vector types
                query_results = []
                for vector_type, points in results.items():
                    query_results.extend(points)

                # Sort by score
                query_results.sort(key=lambda x: x.score, reverse=True)
                all_results.append(query_results)

            except Exception as e:
                log.warning(f"Query failed: {query} - {e}")
                continue

        if not all_results:
            return []

        # Apply fusion method
        if fusion_method == "rrf":
            fused = self.rrf_fuse(all_results, k=rrf_k)
        else:
            # Simple concatenation with deduplication
            fused = []
            for results in all_results:
                fused.extend(results)
            fused = self.deduplicate_results(fused)
            fused.sort(key=lambda x: x.score, reverse=True)

        # Apply final limit and return
        fused_results = fused[:limit]

        add_span_event("qdrant.fusion_complete", {
            "input_queries": len(queries),
            "fused_results": len(fused_results),
            "fusion_method": fusion_method
        })

        return fused_results

    # Instance reset no longer needed - create new instances as needed
