from typing import Any, Dict, List, Optional, TYPE_CHECKING
import asyncio
import time
from dataclasses import dataclass

from app.core.logger import log
from app.core.exceptions import (
    ExpansionMethodError, LLMError,
    LLMUnavailableError, LLMResponseError
)
from app.core.llm_response_processor import LLMResponseProcessor

if TYPE_CHECKING:
    from app.services.llm_manager import LLMManager
    from app.services.qdrant_manager import QdrantManager
    from app.services.prompt_renderer import PromptRenderer


@dataclass
class ExpansionResult:
    """Result from query expansion containing enhanced queries and retrieval results."""
    original_query: str
    expanded_queries: Dict[str, List[str]]  # method -> list of queries
    retrieval_results: List[Any]  # Final fused results
    method_results: Dict[str, List[Any]]  # method -> raw results
    metadata: Dict[str, Any]  # Additional info about expansion process


class ExpansionService:
    """
    Service for advanced query expansion using multiple techniques.

    Implements HyDE, RAG-Fusion, SPLADE PRF, and Self-Ask for enhanced retrieval.
    Dependencies can be injected via constructor or will be created automatically for backward compatibility.
    Prefer using dependency injection from app.core.dependencies.get_expansion_service().
    """

    def __init__(
        self,
        llm_manager: 'LLMManager' = None,
        qdrant_manager: 'QdrantManager' = None,
        prompt_renderer: 'PromptRenderer' = None
    ):
        # LLMManager initialization
        if llm_manager is not None:
            self.llm_manager = llm_manager
            log.debug("ExpansionService using injected LLMManager")
        else:
            from app.services.llm_manager import LLMManager

            self.llm_manager = LLMManager()
            log.warning("ExpansionService creating own LLMManager - consider using dependency injection")

        # QdrantManager initialization
        if qdrant_manager is not None:
            self.qdrant_manager = qdrant_manager
            log.debug("ExpansionService using injected QdrantManager")
        else:
            from app.services.qdrant_manager import QdrantManager

            self.qdrant_manager = QdrantManager()
            log.warning("ExpansionService creating own QdrantManager - consider using dependency injection")

        # PromptRenderer initialization
        if prompt_renderer is not None:
            self.prompt_renderer = prompt_renderer
            log.debug("ExpansionService using injected PromptRenderer")
        else:
            from app.services.prompt_renderer import PromptRenderer

            self.prompt_renderer = PromptRenderer()
            log.warning("ExpansionService creating own PromptRenderer - consider using dependency injection")

    @classmethod
    async def start(cls, llm_manager=None, qdrant_manager=None, prompt_renderer=None):
        """Async factory method for lifespan-managed initialization."""
        instance = cls(
            llm_manager=llm_manager,
            qdrant_manager=qdrant_manager, 
            prompt_renderer=prompt_renderer
        )
        log.info("ExpansionService initialized for lifespan management")
        return instance

    async def aclose(self):
        """Async cleanup for lifespan management."""
        # Clean up any async resources if needed
        log.info("ExpansionService cleaned up")

    async def expand_query(
        self,
        query: str,
        collection: str,
        methods: Optional[List[str]] = None,
        rrf_k: int = 60,
        max_results: int = 10,
        enable_prf: bool = True,
        **query_kwargs
    ) -> ExpansionResult:
        """
        Expand a query using multiple enhancement techniques.
        
        Uses modern LlamaIndex workflows when enabled, falls back to legacy implementation.
        """
        from app.config import get_settings
        settings = get_settings()
        
        if settings.use_llama_index_workflows:
            log.debug("Using LlamaIndex workflows for query expansion")
            return await self._expand_query_modern(
                query, collection, methods, rrf_k, max_results, enable_prf, **query_kwargs
            )
        else:
            log.debug("Using legacy query expansion implementation")
            return await self._expand_query_legacy(
                query, collection, methods, rrf_k, max_results, enable_prf, **query_kwargs
            )

    async def _expand_query_modern(
        self,
        query: str,
        collection: str,
        methods: Optional[List[str]] = None,
        rrf_k: int = 60,
        max_results: int = 10,
        enable_prf: bool = True,
        **query_kwargs
    ) -> ExpansionResult:
        """Modern implementation: generate expanded queries and fuse results (RRF)."""
        try:
            # NOTE: We stick to our QdrantManager path so we can pass
            # strict session filters. No new public methods are introduced.
            log.info("Modern expansion: multi-query + RRF via QdrantManager")
            
            # Generate expanded queries (HyDE-style)
            expanded_queries = {}
            if methods is None:
                methods = ['hyde', 'rag_fusion', 'self_ask']
            
            for method in methods:
                expanded_queries[method] = await self._generate_queries_for_method(query, method)
            
            # Simulate retrieval results - in real implementation this would use QueryFusionRetriever
            all_queries = [query] + [q for queries in expanded_queries.values() for q in queries]
            
            # Use existing Qdrant retrieval but with expanded queries
            retrieval_results = []
            method_results = {}
            
            for i, expanded_query in enumerate(all_queries[:4]):  # Limit to 4 queries like fusion retriever
                try:
                    results = await self.qdrant_manager.query_collection(
                        collection=collection,
                        query_text=expanded_query,
                        **query_kwargs
                    )
                    retrieval_results.extend(results[:max_results//4])  # Distribute results
                    method_results[f"query_{i}"] = results
                except Exception as e:
                    log.warning(f"Query {i} failed: {e}")
                    continue
            
            # Apply RRF fusion using QdrantManager helper (consistent with legacy path)
            result_lists = [lst for lst in method_results.values() if lst]
            if len(result_lists) > 1:
                fused_results = self.qdrant_manager.rrf_fuse(result_lists, k=rrf_k)
            elif result_lists:
                fused_results = self.qdrant_manager.deduplicate_results(result_lists[0])
            else:
                fused_results = []
            
            return ExpansionResult(
                original_query=query,
                expanded_queries=expanded_queries,
                retrieval_results=fused_results[:max_results],
                method_results=method_results,
                metadata={
                    "pipeline": "modern_llamaindex",
                    "fusion_method": "rrf",
                    "rrf_k": rrf_k,
                    "queries_generated": len(all_queries)
                }
            )
            
        except ImportError as e:
            log.warning(f"LlamaIndex fusion retriever not available: {e}, falling back to legacy")
            return await self._expand_query_legacy(
                query, collection, methods, rrf_k, max_results, enable_prf, **query_kwargs
            )
        except Exception as e:
            log.error(f"Modern query expansion failed: {e}, falling back to legacy")
            return await self._expand_query_legacy(
                query, collection, methods, rrf_k, max_results, enable_prf, **query_kwargs
            )

    async def _generate_queries_for_method(self, query: str, method: str) -> List[str]:
        """Dispatch to the concrete query generators by method name."""
        method = (method or "").lower()
        if method == "hyde":
            # collection not needed to compose the prompt here, pass a neutral label
            return await self._generate_hyde_queries(query, collection="general")
        if method == "rag_fusion":
            return await self._generate_fusion_queries(query)
        if method == "self_ask":
            return await self._generate_self_ask_queries(query)
        if method == "prf":
            # PRF builds a single enhanced query from initial results;
            # leave this to _execute_expansion_method so it can retrieve first.
            return [query]
        raise ValueError(f"Unknown expansion method: {method}")

    def build_fusion_retriever(self, *, rrf_k: int = 60, limit: int = 10):
        """
        Lightweight fusion 'retriever' that delegates to QdrantManager.multi_query_fusion.
        This keeps session/privacy filtering under our control and avoids new public APIs.
        """
        async def _retrieve(queries: List[str], collection: str, **kwargs) -> List[Any]:
            return await self.qdrant_manager.multi_query_fusion(
                queries=queries,
                collection=collection,
                fusion_method="rrf",
                rrf_k=rrf_k,
                limit=limit,
                **kwargs
            )
        return _retrieve

    async def _expand_query_legacy(
        self,
        query: str,
        collection: str,
        methods: Optional[List[str]] = None,
        rrf_k: int = 60,
        max_results: int = 10,
        enable_prf: bool = True,
        **query_kwargs
    ) -> ExpansionResult:
        """
        Expand a query using multiple enhancement techniques.

        Args:
            query: Original query string
            collection: Target collection for retrieval
            methods: List of methods to use ['hyde', 'rag_fusion', 'self_ask', 'prf']
            rrf_k: RRF k parameter for fusion
            max_results: Maximum final results to return
            enable_prf: Whether to enable Pseudo Relevance Feedback
            **query_kwargs: Additional arguments for retrieval

        Returns:
            ExpansionResult containing enhanced queries and fused results
        """
        if methods is None:
            methods = ['hyde', 'rag_fusion', 'self_ask']

        log.info(f"Expanding query using methods: {methods}")

        # Store results from each method
        expanded_queries = {}
        method_results = {}
        all_results = []

        # Record start time for performance metrics
        start_time = time.time()

        # Define timing wrapper for accurate per-task measurement
        async def timed_task(task_coro):
            """Wrapper to measure individual task execution time."""
            task_start = time.time()
            try:
                result = await task_coro
                duration = time.time() - task_start
                return (result, duration, None)
            except Exception as e:
                duration = time.time() - task_start
                return (e, duration, None)

        # Create async tasks for each expansion method
        tasks = []
        task_methods = []  # Parallel array - indices guaranteed to align with tasks

        for method in methods:
            if method == 'prf' and not enable_prf:
                continue

            task = timed_task(
                self._execute_expansion_method(method, query, collection, rrf_k, **query_kwargs)
            )
            tasks.append(task)
            task_methods.append(method)

        # Execute all expansion methods in parallel
        log.info(f"Executing {len(tasks)} expansion methods in parallel")
        timed_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Record end time and calculate performance improvement
        parallel_time = time.time() - start_time
        log.info(f"Parallel expansion completed in {parallel_time:.2f}s")

        # Process results and handle exceptions
        method_timings = {}
        for idx, timed_result in enumerate(timed_results):
            method_name = task_methods[idx]

            # Handle gather exceptions (shouldn't happen with return_exceptions=True, but be safe)
            if isinstance(timed_result, Exception):
                log.warning(f"Expansion method {method_name} crashed: {timed_result}")
                continue

            # Unpack timing wrapper: (result, duration, None)
            result, duration, _ = timed_result
            method_timings[method_name] = duration

            if isinstance(result, Exception):
                log.warning(f"Expansion method {method_name} failed after {duration:.2f}s: {result}")
                continue

            # Unpack the result tuple (queries, method_results_list)
            if result and len(result) == 2:
                queries, method_results_list = result
                expanded_queries[method_name] = queries
                method_results[method_name] = method_results_list
                all_results.extend(method_results_list)
                log.info(f"{method_name} completed in {duration:.2f}s with {len(queries)} queries")

        # Calculate and log realistic performance metrics
        if len(tasks) > 1 and method_timings:
            estimated_sequential_time = sum(method_timings.values())
            speedup = estimated_sequential_time / parallel_time if parallel_time > 0 else 1.0

            # Calculate efficiency (percentage of theoretical maximum)
            theoretical_max = len(method_timings)
            efficiency = speedup / theoretical_max * 100 if theoretical_max > 0 else 0

            log.info(
                f"Parallel execution: {speedup:.1f}x speedup "
                f"({efficiency:.0f}% efficiency, theoretical max: {theoretical_max:.0f}x) "
                f"({estimated_sequential_time:.2f}s sequential → {parallel_time:.2f}s parallel)"
            )

            # Warn if efficiency is poor (< 50% of theoretical maximum)
            if efficiency < 50 and method_timings:
                slowest_method = max(method_timings.items(), key=lambda x: x[1])
                log.warning(
                    f"Low parallelization efficiency ({efficiency:.0f}%). "
                    f"Slowest method: {slowest_method[0]} ({slowest_method[1]:.2f}s). "
                    "Possible resource contention or I/O bottleneck. "
                    f"Method timings: {method_timings}"
                )

        # Deduplicate and fuse all results
        deduplicated = self.qdrant_manager.deduplicate_results(all_results)

        # Apply final RRF fusion if we have results from multiple methods
        if len([m for m in method_results.values() if m]) > 1:
            result_lists = [results for results in method_results.values() if results]
            final_results = self.qdrant_manager.rrf_fuse(result_lists, k=rrf_k)
        else:
            final_results = deduplicated

        # Limit final results
        final_results = final_results[:max_results]

        metadata = {
            'methods_used': list(expanded_queries.keys()),
            'total_expanded_queries': sum(len(queries) for queries in expanded_queries.values()),
            'results_before_fusion': len(all_results),
            'results_after_dedup': len(deduplicated),
            'final_results': len(final_results),
            'rrf_k': rrf_k,
            'parallel_execution_time': parallel_time,
            'methods_requested': len(methods),
            'methods_succeeded': len(expanded_queries),
            'method_timings': method_timings,
            'parallel_speedup': sum(method_timings.values()) / parallel_time if parallel_time > 0 and method_timings else 1.0
        }

        return ExpansionResult(
            original_query=query,
            expanded_queries=expanded_queries,
            retrieval_results=final_results,
            method_results=method_results,
            metadata=metadata
        )

    async def _execute_expansion_method(
        self,
        method: str,
        query: str,
        collection: str,
        rrf_k: int,
        **kwargs
    ) -> tuple[List[str], List[Any]]:
        """
        Execute a single expansion method and return (queries, results).

        Args:
            method: Expansion method name ('hyde', 'rag_fusion', 'self_ask', 'prf')
            query: Original query string
            collection: Target collection for retrieval
            rrf_k: RRF k parameter for fusion
            **kwargs: Additional arguments for retrieval

        Returns:
            Tuple of (expanded_queries, retrieval_results)

        Raises:
            ValueError: If method is unknown
        """
        if method == 'hyde':
            queries = await self._generate_hyde_queries(query, collection)
            results = await self._retrieve_hyde_results(queries, collection, **kwargs)
            return (queries, results)

        elif method == 'rag_fusion':
            queries = await self._generate_fusion_queries(query)
            results = await self._retrieve_fusion_results(queries, collection, rrf_k, **kwargs)
            return (queries, results)

        elif method == 'self_ask':
            queries = await self._generate_self_ask_queries(query)
            results = await self._retrieve_self_ask_results(queries, collection, **kwargs)
            return (queries, results)

        elif method == 'prf':
            initial_results = await self._initial_retrieval(query, collection, **kwargs)
            if not initial_results:
                return ([], [])
            expanded_query = await self._generate_prf_query(query, initial_results)
            results = await self._retrieve_prf_results(expanded_query, collection, **kwargs)
            return ([expanded_query], results)

        else:
            raise ValueError(f"Unknown expansion method: {method}")

    async def _generate_hyde_queries(self, query: str, collection: str) -> List[str]:
        """Generate HyDE (Hypothetical Document Embeddings) enhanced queries."""
        try:
            # Generate hypothetical document content
            hyde_content = await self._generate_hyde_content(query, collection)

            # Create enhanced queries combining original with hypothetical content
            queries = [
                query,  # Original query
                hyde_content,  # Pure hypothetical content
                f"{hyde_content}\n\n{query}"  # Combined
            ]

            return queries
        except LLMUnavailableError as e:
            log.error(f"LLM service unavailable for HyDE: {e}")
            raise ExpansionMethodError("hyde", "Content generation service temporarily unavailable")
        except LLMResponseError as e:
            log.warning(f"HyDE generation failed with poor response: {e}")
            # Mark the query as having failed expansion for transparency
            return [f"{query} [expansion_failed:hyde]"]
        except Exception as e:
            log.error(f"Unexpected HyDE failure: {e}")
            # Return original query but mark metadata to indicate failure
            return [f"{query} [expansion_failed:hyde_unexpected]"]

    async def _generate_hyde_content(self, query: str, collection: str) -> str:
        """Generate hypothetical document content using HyDE technique."""
        system_prompt = self.prompt_renderer.render("workflows/expansion/hyde_system.j2")
        user_prompt = self.prompt_renderer.render(
            "workflows/expansion/hyde_user.j2",
            {"query": query, "context": f"Focus on {collection} philosophical tradition"}
        )

        # Generate hypothetical content
        response = await self.llm_manager.aquery(
            f"{system_prompt}\n\n{user_prompt}",
            temperature=0.1  # Lower temperature for more consistent content
        )

        return LLMResponseProcessor.extract_content(response)

    async def _retrieve_hyde_results(self, queries: List[str], collection: str, **kwargs) -> List[Any]:
        """Retrieve results for HyDE queries."""
        all_results = []

        for query in queries:
            try:
                results = await self.qdrant_manager.query_hybrid(
                    query_text=query,
                    collection=collection,
                    limit=kwargs.get('limit', 10),
                    **{k: v for k, v in kwargs.items() if k != 'limit'}
                )

                # Flatten results from all vector types
                for vector_type, points in results.items():
                    all_results.extend(points)

            except Exception as e:
                log.warning(f"HyDE query failed: {query[:50]}... - {e}")
                continue

        return all_results

    async def _generate_fusion_queries(self, query: str, num_queries: int = 4) -> List[str]:
        """Generate multiple perspective queries for RAG-Fusion."""
        try:
            # Use LLM to generate diverse query perspectives
            fusion_prompt = self.prompt_renderer.render(
                "workflows/expansion/rag_fusion_user.j2",
                {"query": query, "num_queries": num_queries}
            )

            response = await self.llm_manager.aquery(
                fusion_prompt,
                temperature=0.7  # Higher temperature for diversity
            )

            # Parse response into separate queries using centralized processor
            queries = LLMResponseProcessor.extract_lines(response, skip_empty=True, skip_numbered=True)

            # Always include original query
            if query not in queries:
                queries.insert(0, query)

            return queries[:num_queries + 1]  # +1 for original

        except LLMUnavailableError as e:
            log.error(f"LLM service unavailable for RAG-Fusion: {e}")
            raise ExpansionMethodError("rag_fusion", "Content generation service temporarily unavailable")
        except LLMResponseError as e:
            log.warning(f"RAG-Fusion generation failed with poor response: {e}")
            return [f"{query} [expansion_failed:rag_fusion]"]
        except Exception as e:
            log.error(f"Unexpected RAG-Fusion failure: {e}")
            return [f"{query} [expansion_failed:rag_fusion_unexpected]"]

    async def _retrieve_fusion_results(self, queries: List[str], collection: str, rrf_k: int, **kwargs) -> List[Any]:
        """Retrieve and fuse results for RAG-Fusion queries."""
        # Use QdrantManager's multi-query fusion capability
        return await self.qdrant_manager.multi_query_fusion(
            queries=queries,
            collection=collection,
            fusion_method="rrf",
            rrf_k=rrf_k,
            limit=kwargs.get('limit', 10),
            **{k: v for k, v in kwargs.items() if k != 'limit'}
        )

    async def _generate_self_ask_queries(self, query: str) -> List[str]:
        """Generate Self-Ask decomposed sub-questions."""
        try:
            system_prompt = self.prompt_renderer.render("workflows/expansion/self_ask_system.j2")
            user_prompt = self.prompt_renderer.render(
                "workflows/expansion/self_ask_user.j2",
                {"query": query}
            )

            response = await self.llm_manager.aquery(
                f"{system_prompt}\n\n{user_prompt}",
                temperature=0.3
            )

            # Parse sub-questions from response
            content = LLMResponseProcessor.extract_content(response)
            sub_questions = []

            # Extract questions from formatted response
            lines = content.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith(('Sub-Question', '**Sub-Question')):
                    # Extract the question part after the colon
                    if ':' in line:
                        question = line.split(':', 1)[1].strip()
                        if question:
                            sub_questions.append(question)

            # Include original query
            all_queries = [query] + sub_questions
            return all_queries

        except LLMUnavailableError as e:
            log.error(f"LLM service unavailable for Self-Ask: {e}")
            raise ExpansionMethodError("self_ask", "Content generation service temporarily unavailable")
        except LLMResponseError as e:
            log.warning(f"Self-Ask generation failed with poor response: {e}")
            return [f"{query} [expansion_failed:self_ask]"]
        except Exception as e:
            log.error(f"Unexpected Self-Ask failure: {e}")
            return [f"{query} [expansion_failed:self_ask_unexpected]"]

    async def _retrieve_self_ask_results(self, queries: List[str], collection: str, **kwargs) -> List[Any]:
        """Retrieve results for Self-Ask decomposed queries."""
        all_results = []

        # Execute queries in parallel for efficiency
        tasks = []
        for query in queries:
            task = self.qdrant_manager.query_hybrid(
                query_text=query,
                collection=collection,
                limit=kwargs.get('limit', 5),  # Fewer results per sub-question
                **{k: v for k, v in kwargs.items() if k != 'limit'}
            )
            tasks.append(task)

        try:
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

            for results in results_list:
                if isinstance(results, Exception):
                    log.warning(f"Self-Ask query failed: {results}")
                    continue

                # Flatten results from all vector types
                for vector_type, points in results.items():
                    all_results.extend(points)

        except Exception as e:
            log.warning(f"Self-Ask parallel retrieval failed: {e}")

        return all_results

    async def _initial_retrieval(self, query: str, collection: str, **kwargs) -> List[Any]:
        """Perform initial retrieval for PRF (Pseudo Relevance Feedback)."""
        try:
            results = await self.qdrant_manager.query_hybrid(
                query_text=query,
                collection=collection,
                limit=5,  # Small initial set for PRF
                **{k: v for k, v in kwargs.items() if k != 'limit'}
            )

            # Flatten and return top results
            all_results = []
            for vector_type, points in results.items():
                all_results.extend(points)

            # Sort by score and return top results
            all_results.sort(key=lambda x: x.score, reverse=True)
            return all_results[:3]  # Top 3 for PRF

        except Exception as e:
            log.warning(f"Initial PRF retrieval failed: {e}")
            return []

    async def _generate_prf_query(self, original_query: str, initial_results: List[Any]) -> str:
        """Generate PRF-enhanced query using initial retrieval results."""
        try:
            # Extract key terms from top results using SPLADE if available
            key_terms = []

            for result in initial_results:
                if hasattr(result, 'payload') and 'text' in result.payload:
                    text = result.payload['text'][:500]  # First 500 chars

                    # Use SPLADE to extract important terms
                    splade_vector = await self.llm_manager.generate_splade_vector(text)

                    # Get top terms from SPLADE vector
                    if 'indices' in splade_vector and 'values' in splade_vector:
                        indices = splade_vector['indices']
                        values = splade_vector['values']

                        # Get top 5 terms by weight
                        top_indices = sorted(zip(indices, values), key=lambda x: x[1], reverse=True)[:5]

                        for idx, weight in top_indices:
                            term = self.llm_manager.splade_tokenizer.decode([idx])
                            if len(term.strip()) > 2:  # Filter out short tokens
                                key_terms.append(term.strip())

            # Combine original query with key terms
            unique_terms = list(set(key_terms))[:10]  # Top 10 unique terms
            enhanced_query = f"{original_query} {' '.join(unique_terms)}"

            return enhanced_query

        except Exception as e:
            log.warning(f"PRF query generation failed: {e}")
            return original_query

    async def _retrieve_prf_results(self, enhanced_query: str, collection: str, **kwargs) -> List[Any]:
        """Retrieve results using PRF-enhanced query."""
        try:
            results = await self.qdrant_manager.query_hybrid(
                query_text=enhanced_query,
                collection=collection,
                limit=kwargs.get('limit', 10),
                **{k: v for k, v in kwargs.items() if k != 'limit'}
            )

            # Flatten results
            all_results = []
            for vector_type, points in results.items():
                all_results.extend(points)

            return all_results

        except Exception as e:
            log.warning(f"PRF retrieval failed: {e}")
            return []
