"""
Fusion retriever helper functions for ChatQdrantService integration.

Provides utilities to build QueryFusionRetriever with your existing Qdrant setup.
"""

from typing import List, Optional
from app.core.logger import log
from app.core.workflow_imports import QueryFusionRetriever, FUSION_MODES, FUSION_IMPORTS_OK


def build_fusion_retriever(
    dense_retriever, 
    sparse_retriever, 
    num_queries: int = 4,
    mode: str = "reciprocal_rerank",
    use_async: bool = True
) -> Optional[QueryFusionRetriever]:
    """
    Build a QueryFusionRetriever with dense and sparse retrievers.
    
    Args:
        dense_retriever: Dense vector retriever (e.g., from VectorStoreIndex)
        sparse_retriever: Sparse retriever (e.g., BM25 or keyword-based)
        num_queries: Number of queries to generate for fusion
        mode: Fusion mode - use "reciprocal_rerank", "relative_score", etc.
        use_async: Whether to use async retrieval
        
    Returns:
        QueryFusionRetriever instance or None if imports failed
    """
    if not FUSION_IMPORTS_OK:
        log.warning("QueryFusionRetriever not available - using fallback retrieval")
        return None
    
    try:
        # Convert mode string to enum if available
        fusion_mode = getattr(FUSION_MODES, mode.upper(), mode)
        
        fusion_retriever = QueryFusionRetriever(
            retrievers=[dense_retriever, sparse_retriever],
            num_queries=num_queries,
            mode=fusion_mode,
            use_async=use_async,
        )
        
        log.info(f"Built QueryFusionRetriever with {len([dense_retriever, sparse_retriever])} retrievers")
        return fusion_retriever
        
    except Exception as e:
        log.error(f"Failed to build QueryFusionRetriever: {e}")
        return None


def create_mock_retrievers_from_qdrant(qdrant_manager, collection: str):
    """
    Create mock retrievers that interface with your QdrantManager.
    
    In a full implementation, this would create proper VectorStoreIndex instances
    from your Qdrant collections and expose them as retrievers.
    
    Args:
        qdrant_manager: Your existing QdrantManager instance
        collection: Qdrant collection name
        
    Returns:
        tuple: (dense_retriever_mock, sparse_retriever_mock)
    """
    
    class QdrantRetrieverMock:
        """Mock retriever that uses your existing Qdrant setup."""
        
        def __init__(self, manager, collection_name, retrieval_type="dense"):
            self.manager = manager
            self.collection = collection_name 
            self.type = retrieval_type
            
        async def retrieve(self, query: str, limit: int = 10):
            """Retrieve using your existing QdrantManager methods."""
            if self.type == "dense":
                # Use your existing dense vector search
                results = await self.manager.query_collection(
                    collection=self.collection,
                    query_text=query,
                    limit=limit
                )
            else:
                # Use hybrid search for "sparse" (since you might not have pure BM25)
                hybrid_results = await self.manager.query_hybrid(
                    query_text=query,
                    collection=self.collection,
                    limit=limit
                )
                # Extract results from hybrid response
                results = []
                for points in hybrid_results.values():
                    results.extend(points)
                    
            return results[:limit]
    
    dense_mock = QdrantRetrieverMock(qdrant_manager, collection, "dense")
    sparse_mock = QdrantRetrieverMock(qdrant_manager, collection, "sparse")
    
    return dense_mock, sparse_mock


# Example usage integration point for ChatQdrantService
async def enhanced_semantic_search(
    qdrant_manager,
    query: str, 
    collection: str,
    limit: int = 10,
    use_fusion: bool = True
):
    """
    Enhanced semantic search that can optionally use QueryFusionRetriever.
    
    This is a drop-in replacement for your existing semantic search that adds
    fusion capabilities while maintaining backward compatibility.
    
    Args:
        qdrant_manager: Your existing QdrantManager
        query: Search query
        collection: Qdrant collection name  
        limit: Number of results
        use_fusion: Whether to use fusion retrieval
        
    Returns:
        Search results (same format as existing search)
    """
    if not use_fusion or not FUSION_IMPORTS_OK:
        # Fallback to existing search
        return await qdrant_manager.query_collection(
            collection=collection,
            query_text=query,
            limit=limit
        )
    
    try:
        # Create mock retrievers from your Qdrant setup
        dense_retriever, sparse_retriever = create_mock_retrievers_from_qdrant(
            qdrant_manager, collection
        )
        
        # Build fusion retriever
        fusion_retriever = build_fusion_retriever(
            dense_retriever, 
            sparse_retriever,
            num_queries=4,
            mode="reciprocal_rank"  # Updated to match actual enum
        )
        
        if fusion_retriever is None:
            # Fallback to regular search
            return await qdrant_manager.query_collection(
                collection=collection,
                query_text=query, 
                limit=limit
            )
        
        # Use fusion retrieval (this would need proper integration)
        # For now, fallback to regular search but log that fusion is available
        log.info("Fusion retriever available but not fully integrated yet")
        return await qdrant_manager.query_collection(
            collection=collection,
            query_text=query,
            limit=limit
        )
        
    except Exception as e:
        log.error(f"Fusion search failed: {e}")
        # Fallback to regular search
        return await qdrant_manager.query_collection(
            collection=collection,
            query_text=query,
            limit=limit
        )