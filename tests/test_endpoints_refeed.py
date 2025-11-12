import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
import json


@pytest.fixture
def mock_services():
    """Mock all external services for endpoint testing."""
    with patch('app.services.qdrant_manager.QdrantManager') as mock_qdrant, \
         patch('app.services.llm_manager.LLMManager') as mock_llm:

        # Configure QdrantManager mock
        mock_qdrant_instance = MagicMock()
        mock_qdrant_instance.gather_points_and_sort = AsyncMock()
        mock_qdrant.return_value = mock_qdrant_instance

        # Configure LLMManager mock
        mock_llm_instance = MagicMock()
        mock_llm_instance.achat = AsyncMock()
        mock_llm_instance.avet = AsyncMock()
        mock_llm_instance.set_llm_context_window = MagicMock()
        mock_llm.return_value = mock_llm_instance

        yield {
            'qdrant': mock_qdrant_instance,
            'llm': mock_llm_instance
        }


@pytest.fixture
def client(mock_services):
    """Create FastAPI test client with mocked services."""
    from app.main import _main
    import os

    # Set test environment
    os.environ["APP_ENV"] = "test"
    os.environ["LOG_LEVEL"] = "ERROR"

    # Import after setting env vars
    from app.router import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    return TestClient(app)


class TestAskPhilosophyRefeed:
    """Test refeed functionality in /ask_philosophy endpoint."""

    def test_ask_philosophy_refeed_true(self, client, mock_services):
        """Test /ask_philosophy with refeed=true passes parameter correctly."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.message.content = "Virtue ethics response"
        mock_response.raw = MagicMock()
        mock_services['llm'].achat.return_value = mock_response
        mock_services['qdrant'].gather_points_and_sort.return_value = []

        # Make request with refeed=true
        response = client.post(
            "/ask_philosophy?refeed=true&immersive=false&temperature=0.3",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with refeed=True
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is True

    def test_ask_philosophy_refeed_false(self, client, mock_services):
        """Test /ask_philosophy with refeed=false passes parameter correctly."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.message.content = "Virtue ethics response"
        mock_response.raw = MagicMock()
        mock_services['llm'].achat.return_value = mock_response
        mock_services['qdrant'].gather_points_and_sort.return_value = []

        # Make request with refeed=false
        response = client.post(
            "/ask_philosophy?refeed=false&immersive=false&temperature=0.3",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with refeed=False
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is False

    def test_ask_philosophy_refeed_default(self, client, mock_services):
        """Test /ask_philosophy with default refeed value (should be True)."""
        # Configure mock response
        mock_response = MagicMock()
        mock_response.message.content = "Virtue ethics response"
        mock_response.raw = MagicMock()
        mock_services['llm'].achat.return_value = mock_response
        mock_services['qdrant'].gather_points_and_sort.return_value = []

        # Make request without refeed parameter
        response = client.post(
            "/ask_philosophy?immersive=false&temperature=0.3",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with refeed=True (default)
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is True


class TestQueryHybridRefeed:
    """Test refeed functionality in /query_hybrid endpoint."""

    def test_query_hybrid_refeed_true(self, client, mock_services):
        """Test /query_hybrid with refeed=true passes parameter correctly."""
        mock_services['qdrant'].gather_points_and_sort.return_value = {"test": "data"}

        # Make request with refeed=true
        response = client.post(
            "/query_hybrid?refeed=true&vet_mode=false&raw_mode=false&limit=10",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with refeed=True
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is True

    def test_query_hybrid_refeed_false(self, client, mock_services):
        """Test /query_hybrid with refeed=false passes parameter correctly."""
        mock_services['qdrant'].gather_points_and_sort.return_value = {"test": "data"}

        # Make request with refeed=false
        response = client.post(
            "/query_hybrid?refeed=false&vet_mode=false&raw_mode=false&limit=10",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with refeed=False
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is False

    def test_query_hybrid_refeed_with_raw_mode(self, client, mock_services):
        """Test /query_hybrid with refeed=true and raw_mode=true."""
        mock_services['qdrant'].gather_points_and_sort.return_value = {
            "Aristotle": {"test": "main_data"},
            "Meta Collection": {"test": "meta_data"}
        }

        # Make request with refeed=true and raw_mode=true
        response = client.post(
            "/query_hybrid?refeed=true&vet_mode=false&raw_mode=true&limit=10",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with correct parameters
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is True
        assert call_args[1]['raw_mode'] is True

    def test_query_hybrid_refeed_default(self, client, mock_services):
        """Test /query_hybrid with default refeed value (should be True)."""
        mock_services['qdrant'].gather_points_and_sort.return_value = {"test": "data"}

        # Make request without refeed parameter
        response = client.post(
            "/query_hybrid?vet_mode=false&raw_mode=false&limit=10",
            json={
                "query_str": "What is virtue ethics?",
                "collection": "Aristotle"
            }
        )

        assert response.status_code == 200

        # Verify gather_points_and_sort was called with refeed=True (default)
        mock_services['qdrant'].gather_points_and_sort.assert_called_once()
        call_args = mock_services['qdrant'].gather_points_and_sort.call_args
        assert call_args[1]['refeed'] is True