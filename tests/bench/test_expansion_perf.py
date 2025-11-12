"""
Simplified performance benchmark for ExpansionService patches.

Tests that the surgical patches work correctly without triggering
full service initialization that requires configuration setup.
"""

import asyncio
import time
import statistics as stats
import pytest
from unittest.mock import AsyncMock, MagicMock
import os

from app.services.expansion_service import ExpansionService

QUERIES = [
    "how does stoicism differ from epicureanism?",
    "moral luck examples in everyday life", 
]


@pytest.mark.asyncio
async def test_build_fusion_retriever_unit():
    """Test the fusion retriever builder creates working retriever function."""
    
    # Create a minimal mock qdrant manager directly (no full initialization)
    mock_qdrant_instance = AsyncMock()
    mock_qdrant_instance.multi_query_fusion.return_value = [
        {"id": f"fusion_{i}", "score": 0.95 - i*0.05} for i in range(8)
    ]
    
    # Create minimal mock dependencies to avoid full initialization
    mock_llm = AsyncMock()
    mock_renderer = AsyncMock()
    
    svc = ExpansionService(
        llm_manager=mock_llm,
        qdrant_manager=mock_qdrant_instance,
        prompt_renderer=mock_renderer
    )
    
    # Build fusion retriever
    retriever = svc.build_fusion_retriever(rrf_k=30, limit=5)
    
    # Test it works
    queries = ["test query 1", "test query 2"]
    results = await retriever(queries, "test_collection", session_id="test123")
    
    # Verify it called the right method with right args
    mock_qdrant_instance.multi_query_fusion.assert_called_once_with(
        queries=queries,
        collection="test_collection",
        fusion_method="rrf",
        rrf_k=30,
        limit=5,
        session_id="test123"
    )
    
    # Verify results returned
    assert len(results) == 8
    assert results[0]["id"] == "fusion_0"
    assert results[0]["score"] == 0.95


def test_generate_queries_for_method_unit():
    """Test the query method dispatcher works correctly."""
    
    # Create minimal mocks to avoid initialization
    mock_llm = MagicMock()
    mock_qdrant = MagicMock() 
    mock_renderer = MagicMock()
    
    svc = ExpansionService(
        llm_manager=mock_llm,
        qdrant_manager=mock_qdrant,
        prompt_renderer=mock_renderer
    )
    
    # Mock the actual query generation methods
    svc._generate_hyde_queries = AsyncMock(return_value=["hyde query 1", "hyde query 2"])
    svc._generate_fusion_queries = AsyncMock(return_value=["fusion query 1", "fusion query 2"]) 
    svc._generate_self_ask_queries = AsyncMock(return_value=["self ask query 1"])
    
    # Test dispatching works
    async def test_dispatch():
        # Test hyde
        result = await svc._generate_queries_for_method("test query", "hyde")
        assert result == ["hyde query 1", "hyde query 2"]
        svc._generate_hyde_queries.assert_called_with("test query", collection="general")
        
        # Test rag_fusion
        result = await svc._generate_queries_for_method("test query", "rag_fusion")
        assert result == ["fusion query 1", "fusion query 2"]
        svc._generate_fusion_queries.assert_called_with("test query")
        
        # Test self_ask
        result = await svc._generate_queries_for_method("test query", "self_ask")
        assert result == ["self ask query 1"]
        svc._generate_self_ask_queries.assert_called_with("test query")
        
        # Test prf
        result = await svc._generate_queries_for_method("test query", "prf")
        assert result == ["test query"]  # Should return original query
        
        # Test unknown method
        with pytest.raises(ValueError, match="Unknown expansion method"):
            await svc._generate_queries_for_method("test query", "unknown")
    
    # Run the async test
    asyncio.run(test_dispatch())


def test_surgical_patches_applied():
    """Verify that all expected methods are available after patches."""
    
    # Check methods exist without instantiating (avoids initialization)
    assert hasattr(ExpansionService, '_generate_queries_for_method')
    assert hasattr(ExpansionService, 'build_fusion_retriever')
    assert hasattr(ExpansionService, 'expand_query')  # Original method preserved
    
    # Verify method signatures
    import inspect
    
    # _generate_queries_for_method should accept query and method
    sig = inspect.signature(ExpansionService._generate_queries_for_method)
    params = list(sig.parameters.keys())
    assert 'query' in params
    assert 'method' in params
    
    # build_fusion_retriever should accept rrf_k and limit as keyword args  
    sig = inspect.signature(ExpansionService.build_fusion_retriever)
    params = sig.parameters
    assert 'rrf_k' in params
    assert 'limit' in params
    assert params['rrf_k'].default == 60
    assert params['limit'].default == 10


if __name__ == "__main__":
    # Allow running tests directly
    import sys
    import os
    
    # Add project root to path for direct execution
    project_root = os.path.join(os.path.dirname(__file__), "../..")
    sys.path.insert(0, project_root)
    
    print("🔧 Running surgical patch verification...")
    test_surgical_patches_applied()
    print("✅ All expected methods are available!")
    
    print("🧪 Running unit tests...")
    test_generate_queries_for_method_unit()
    print("✅ Query method dispatch works!")
    
    asyncio.run(test_build_fusion_retriever_unit())
    print("✅ Fusion retriever builder works!")
    
    print("🎉 Surgical patches verified successfully!")