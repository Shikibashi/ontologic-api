import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.qdrant_manager import QdrantManager
from app.core.models import HybridQueryRequest


@pytest.fixture
def mock_qdrant_manager():
    """Create a QdrantManager instance with mocked dependencies."""
    with patch('app.services.qdrant_manager.AsyncQdrantClient'), \
         patch('app.services.llm_manager.LLMManager'):
        manager = QdrantManager()
        manager.qclient = AsyncMock()
        manager.llm_manager = MagicMock()
        return manager


@pytest.fixture
def sample_request():
    """Sample HybridQueryRequest for testing."""
    return HybridQueryRequest(
        query_str="What is virtue ethics?",
        collection="Aristotle"
    )


@pytest.fixture
def meta_collection_request():
    """Sample request for Meta Collection (should not trigger refeed)."""
    return HybridQueryRequest(
        query_str="What is virtue ethics?",
        collection="Meta Collection"
    )


class TestRefeedFunctionality:
    """Test cases for the refeed functionality in QdrantManager."""

    @pytest.mark.asyncio
    async def test_gather_points_no_refeed(self, mock_qdrant_manager, sample_request):
        """Test gather_points_and_sort with refeed=False does not fetch meta nodes."""
        # Mock the query_hybrid method
        mock_nodes = {"sparse_original": [MagicMock()]}
        mock_qdrant_manager.query_hybrid = AsyncMock(return_value=mock_nodes)
        mock_qdrant_manager.select_top_nodes = MagicMock(return_value=[])

        # Call with refeed=False
        await mock_qdrant_manager.gather_points_and_sort(
            sample_request,
            refeed=False
        )

        # Verify query_hybrid was called only once (for main collection)
        assert mock_qdrant_manager.query_hybrid.call_count == 1

        # Verify it was called with the original query string
        call_args = mock_qdrant_manager.query_hybrid.call_args
        assert call_args[0][0] == sample_request.query_str
        assert call_args[0][1] == sample_request.collection

    @pytest.mark.asyncio
    async def test_gather_points_with_refeed(self, mock_qdrant_manager, sample_request):
        """Test gather_points_and_sort with refeed=True fetches meta nodes first."""
        # Mock meta nodes response
        mock_meta_nodes = {
            "sparse_original": [MagicMock(payload={"text": "Meta context text"}, score=0.9)]
        }

        # Mock main collection response
        mock_main_nodes = {"sparse_original": [MagicMock()]}

        # Configure query_hybrid to return different responses
        def mock_query_hybrid(*args, **kwargs):
            if args[1] == "Meta Collection":
                return mock_meta_nodes
            else:
                return mock_main_nodes

        mock_qdrant_manager.query_hybrid = AsyncMock(side_effect=mock_query_hybrid)
        mock_qdrant_manager.select_top_nodes = MagicMock(return_value=[])

        # Call with refeed=True
        await mock_qdrant_manager.gather_points_and_sort(
            sample_request,
            refeed=True
        )

        # Verify query_hybrid was called twice (meta + main collection)
        assert mock_qdrant_manager.query_hybrid.call_count == 2

        # Verify first call was to Meta Collection
        first_call = mock_qdrant_manager.query_hybrid.call_args_list[0]
        assert first_call[0][1] == "Meta Collection"

        # Verify second call was to main collection with enhanced query
        second_call = mock_qdrant_manager.query_hybrid.call_args_list[1]
        assert second_call[0][1] == sample_request.collection
        # Query should be enhanced with meta context
        enhanced_query = second_call[0][0]
        assert sample_request.query_str in enhanced_query
        assert "Meta context text" in enhanced_query

    @pytest.mark.asyncio
    async def test_gather_points_meta_collection_no_refeed(self, mock_qdrant_manager, meta_collection_request):
        """Test that Meta Collection requests don't trigger refeed even when refeed=True."""
        mock_nodes = {"sparse_original": [MagicMock()]}
        mock_qdrant_manager.query_hybrid = AsyncMock(return_value=mock_nodes)
        mock_qdrant_manager.select_top_nodes = MagicMock(return_value=[])

        # Call with refeed=True but Meta Collection
        await mock_qdrant_manager.gather_points_and_sort(
            meta_collection_request,
            refeed=True
        )

        # Verify query_hybrid was called only once (no meta refeed for Meta Collection)
        assert mock_qdrant_manager.query_hybrid.call_count == 1

        # Verify it was called with the original query
        call_args = mock_qdrant_manager.query_hybrid.call_args
        assert call_args[0][0] == meta_collection_request.query_str
        assert call_args[0][1] == "Meta Collection"

    @pytest.mark.asyncio
    async def test_gather_points_raw_mode_with_refeed(self, mock_qdrant_manager, sample_request):
        """Test raw_mode returns both collections when refeed=True."""
        # Mock responses
        mock_meta_nodes = {"sparse_original": [MagicMock(payload={"text": "Meta text"}, score=0.9)]}
        mock_main_nodes = {"sparse_original": [MagicMock()]}

        def mock_query_hybrid(*args, **kwargs):
            if args[1] == "Meta Collection":
                return mock_meta_nodes
            else:
                return mock_main_nodes

        mock_qdrant_manager.query_hybrid = AsyncMock(side_effect=mock_query_hybrid)

        # Call with raw_mode=True and refeed=True
        result = await mock_qdrant_manager.gather_points_and_sort(
            sample_request,
            raw_mode=True,
            refeed=True
        )

        # Verify result contains both collections
        assert isinstance(result, dict)
        assert sample_request.collection in result
        assert "Meta Collection" in result
        assert result[sample_request.collection] == mock_main_nodes
        assert result["Meta Collection"] == mock_meta_nodes