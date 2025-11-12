import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
import os


@pytest.fixture
def mock_environment():
    """Set up mock environment variables for testing."""
    with patch.dict(os.environ, {
        'QDRANT_API_KEY': 'test-api-key',
        'LOG_LEVEL': 'INFO',
        'ONTOLOGIC_DB_URL': 'sqlite:///./test.db'
    }):
        yield


@pytest.fixture
def mock_all_services():
    """Mock all external services for E2E testing."""
    with patch('app.services.qdrant_manager.AsyncQdrantClient'), \
         patch('app.services.llm_manager.Ollama'), \
         patch('app.services.llm_manager.OllamaEmbedding'), \
         patch('app.services.llm_manager.AutoTokenizer'), \
         patch('app.services.llm_manager.AutoModelForMaskedLM'), \
         patch('app.core.database.init_db'):

        # Mock QdrantManager
        qdrant_mock = MagicMock()
        qdrant_mock.query_hybrid = AsyncMock(return_value={
            "sparse_original": [
                MagicMock(id="test1", score=0.9, payload={"text": "Test content", "author": "Test Author"})
            ]
        })
        qdrant_mock.gather_points_and_sort = AsyncMock(return_value=[
            MagicMock(id="test1", payload={"text": "Test content"})
        ])
        # Create proper collection mocks with string names
        aristotle_collection = MagicMock()
        aristotle_collection.name = "Aristotle"
        meta_collection = MagicMock()
        meta_collection.name = "Meta Collection"
        
        qdrant_mock.get_collections = AsyncMock(return_value=MagicMock(
            collections=[aristotle_collection, meta_collection]
        ))

        # Mock LLMManager
        llm_mock = MagicMock()
        llm_response = MagicMock()
        llm_response.message.content = "Generated philosophical content"
        llm_response.raw = {
            "model": "test-model",
            "created_at": "2024-01-01T00:00:00Z",
            "done": True,
            "done_reason": "stop",
            "total_duration": 1000000,
            "load_duration": 100000,
            "prompt_eval_count": 100,
            "prompt_eval_duration": 500000,
            "eval_count": 50,
            "eval_duration": 400000,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
        llm_mock.aquery = AsyncMock(return_value=llm_response)
        llm_mock.achat = AsyncMock(return_value=llm_response)
        llm_mock.avet = AsyncMock(return_value=llm_response)

        with patch('app.services.qdrant_manager.QdrantManager', return_value=qdrant_mock), \
             patch('app.services.llm_manager.LLMManager', return_value=llm_mock):
            yield {
                "llm": llm_mock,
                "qdrant": qdrant_mock,
                "cache": None
            }


@pytest.fixture
def client(mock_all_services, mock_environment):
    """Create test client with all services mocked using dependency overrides."""
    from fastapi import FastAPI
    from app.router import router
    from app.core import dependencies as deps
    from unittest.mock import AsyncMock

    app = FastAPI(title="E2E Test App")
    app.include_router(router)

    # Create additional service mocks
    mock_cache_service = AsyncMock()
    mock_cache_service.get.return_value = None
    mock_cache_service.set.return_value = True
    
    mock_prompt_renderer = AsyncMock()
    mock_prompt_renderer.render.return_value = "test prompt"
    
    mock_expansion_service = AsyncMock()
    mock_expansion_service.expand_query.return_value = ["expanded query"]
    
    mock_chat_history_service = AsyncMock()
    mock_chat_history_service.get_conversation_history.return_value = []
    
    mock_chat_qdrant_service = AsyncMock()
    mock_chat_qdrant_service.store_message_embedding.return_value = None
    
    mock_paper_workflow = AsyncMock()
    test_draft_id = "12345678-1234-1234-1234-123456789abc"
    mock_paper_workflow.create_draft.return_value = test_draft_id

    # Success payload for generate_sections
    generate_sections_success = {
        "draft_id": test_draft_id,
        "sections_generated": ["abstract", "introduction"],
        "sections_failed": [],
        "total_sections": 2,
        "final_status": "completed"
    }

    # Define side_effect for generate_sections to fail on invalid draft IDs
    def fail_on_invalid_generate_sections(*args, **kwargs):
        draft_id = kwargs.get('draft_id') or (args[0] if args else None)
        if draft_id == "invalid-draft-id":
            raise ValueError("Invalid draft ID")
        return generate_sections_success

    mock_paper_workflow.generate_sections.side_effect = fail_on_invalid_generate_sections
    
    # Mock get_draft_status to return different states based on call count
    status_call_count = 0
    async def mock_get_draft_status(draft_id):
        nonlocal status_call_count
        status_call_count += 1
        base_status = {
            "draft_id": draft_id,
            "title": "Test Paper on Virtue Ethics",
            "topic": "What is virtue ethics in Aristotelian philosophy?",
            "collection": "Aristotle",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "sections": {"abstract": None, "introduction": None},
            "has_review": False,
            "suggestions_count": 0
        }
        if status_call_count == 1:
            base_status.update({
                "status": "created",
                "progress": {"completed_sections": 0}
            })
        elif status_call_count == 2:
            base_status.update({
                "status": "generated", 
                "progress": {"completed_sections": 2},
                "sections": {"abstract": "Generated abstract", "introduction": "Generated introduction"}
            })
        else:
            # Final status after apply
            base_status.update({
                "status": "completed", 
                "progress": {"completed_sections": 2},
                "sections": {"abstract": "Generated abstract", "introduction": "Generated introduction"},
                "has_review": True,
                "suggestions_count": 2
            })
        return base_status
    
    mock_paper_workflow.get_draft_status.side_effect = mock_get_draft_status
    mock_paper_workflow.apply_suggestions.return_value = {"status": "success"}

    mock_review_workflow = AsyncMock()

    # Success payload for review_draft
    review_draft_success = {
        "draft_id": test_draft_id,
        "review_id": "review-123",
        "status": "completed",
        "summary": {"score": 85, "issues": []},
        "blocking_issues": 0,
        "verification_coverage": "high"
    }

    # Define side_effect for review_draft to fail on invalid draft IDs
    def fail_on_invalid_review_draft(*args, **kwargs):
        draft_id = kwargs.get('draft_id') or (args[0] if args else None)
        if draft_id == "invalid-draft-id":
            raise ValueError("Invalid draft ID")
        return review_draft_success

    mock_review_workflow.review_draft.side_effect = fail_on_invalid_review_draft
    mock_review_workflow.get_review_data.return_value = {
        "review_data": {"score": 85},
        "suggestions": ["suggestion 1", "suggestion 2"]
    }
    
    mock_auth_service = AsyncMock()
    mock_auth_service.verify_token.return_value = {"user_id": "test-user"}
    # Fix the auth service methods to return proper values, not coroutines
    mock_auth_service.get_available_providers = MagicMock(return_value={"github": {"name": "GitHub"}})
    mock_auth_service.create_anonymous_session = AsyncMock(return_value="test-session-123")
    mock_auth_service.is_oauth_enabled = MagicMock(return_value=False)
    
    # Payment service mocks (can be None for graceful degradation)
    mock_payment_service = None
    mock_subscription_manager = None
    mock_billing_service = None

    # Override all dependencies to use mocks
    app.dependency_overrides[deps.get_llm_manager] = lambda: mock_all_services["llm"]
    app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_all_services["qdrant"]
    app.dependency_overrides[deps.get_cache_service] = lambda: mock_cache_service
    app.dependency_overrides[deps.get_prompt_renderer] = lambda: mock_prompt_renderer
    app.dependency_overrides[deps.get_expansion_service] = lambda: mock_expansion_service
    app.dependency_overrides[deps.get_chat_history_service] = lambda: mock_chat_history_service
    app.dependency_overrides[deps.get_chat_qdrant_service] = lambda: mock_chat_qdrant_service
    app.dependency_overrides[deps.get_paper_workflow] = lambda: mock_paper_workflow
    app.dependency_overrides[deps.get_review_workflow] = lambda: mock_review_workflow
    app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[deps.get_payment_service] = lambda: mock_payment_service
    app.dependency_overrides[deps.get_subscription_manager] = lambda: mock_subscription_manager
    app.dependency_overrides[deps.get_billing_service] = lambda: mock_billing_service
    
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


class TestE2EWorkflowSmoke:
    """End-to-end smoke tests for the complete workflow system."""

    def test_create_generate_review_apply_status_flow(self, client):
        """
        Smoke test for complete workflow: create → generate → review → apply → status

        This tests the happy path through all major workflow operations.
        """
        # Step 1: Create a draft
        create_response = client.post("/workflows/create", json={
            "title": "Test Paper on Virtue Ethics",
            "topic": "What is virtue ethics in Aristotelian philosophy?",
            "collection": "Aristotle",
            "immersive_mode": False,
            "temperature": 0.3
        })

        assert create_response.status_code == 200
        create_data = create_response.json()
        assert "draft_id" in create_data
        assert create_data["status"] == "created"
        draft_id = create_data["draft_id"]

        # Step 2: Check initial status
        status_response = client.get(f"/workflows/{draft_id}/status")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["status"] == "created"
        assert status_data["progress"]["completed_sections"] == 0

        # Step 3: Generate sections
        generate_response = client.post(f"/workflows/{draft_id}/generate", json={
            "sections": ["abstract", "introduction"],
            "use_expansion": True,
            "expansion_methods": ["hyde", "rag_fusion"]
        })

        assert generate_response.status_code == 200
        generate_data = generate_response.json()
        assert generate_data["final_status"] == "completed"
        assert "abstract" in generate_data["sections_generated"]
        assert "introduction" in generate_data["sections_generated"]

        # Step 4: Check status after generation
        status_response = client.get(f"/workflows/{draft_id}/status")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["status"] == "generated"
        assert status_data["progress"]["completed_sections"] >= 2

        # Step 5: Perform AI review
        review_response = client.post(f"/workflows/{draft_id}/ai-review", json={
            "rubric": ["accuracy", "argument", "coherence"],
            "severity_gate": "medium",
            "max_evidence_per_question": 3
        })

        assert review_response.status_code == 200
        review_data = review_response.json()
        assert review_data["status"] == "completed"
        assert "review_id" in review_data

        # Step 6: Check review data
        with patch('app.services.paper_service.PaperDraftService') as mock_service:
            mock_draft = MagicMock()
            mock_draft.review_data = {
                "review_data": {"score": 85, "issues": []},
                "suggestions": ["suggestion 1", "suggestion 2"]
            }
            mock_service.get_draft = AsyncMock(return_value=mock_draft)
            
            review_detail_response = client.get(f"/workflows/{draft_id}/review")
            assert review_detail_response.status_code == 200
            review_detail_data = review_detail_response.json()
            assert "review_data" in review_detail_data
            assert "suggestions" in review_detail_data

        # Step 7: Apply suggestions
        apply_response = client.post(f"/workflows/{draft_id}/apply", json={
            "accept_all": True
        })

        assert apply_response.status_code == 200
        apply_data = apply_response.json()
        assert apply_data["status"] == "success"

        # Step 8: Final status check
        final_status_response = client.get(f"/workflows/{draft_id}/status")
        assert final_status_response.status_code == 200
        final_status_data = final_status_response.json()
        assert final_status_data["status"] == "completed"

    def test_immersive_mode_workflow(self, client):
        """Test workflow with immersive philosopher mode enabled."""
        # Create draft with immersive mode
        create_response = client.post("/workflows/create", json={
            "title": "First-Person Virtue Ethics",
            "topic": "My understanding of eudaimonia",
            "collection": "Aristotle",
            "immersive_mode": True,
            "temperature": 0.5
        })

        assert create_response.status_code == 200
        draft_id = create_response.json()["draft_id"]

        # Generate with immersive mode
        generate_response = client.post(f"/workflows/{draft_id}/generate", json={
            "sections": ["introduction"],
            "use_expansion": True
        })

        assert generate_response.status_code == 200
        assert generate_response.json()["final_status"] == "completed"

    def test_selective_suggestion_application(self, client):
        """Test applying suggestions selectively by section."""
        # Create and generate content
        create_response = client.post("/workflows/create", json={
            "title": "Selective Review Test",
            "topic": "Test topic",
            "collection": "Aristotle"
        })
        draft_id = create_response.json()["draft_id"]

        client.post(f"/workflows/{draft_id}/generate", json={
            "sections": ["abstract", "introduction", "conclusion"]
        })

        # Review the content
        client.post(f"/workflows/{draft_id}/ai-review", json={
            "severity_gate": "low"
        })

        # Apply suggestions only for specific sections
        apply_response = client.post(f"/workflows/{draft_id}/apply", json={
            "accept_sections": ["introduction", "conclusion"]
        })

        assert apply_response.status_code == 200
        assert apply_response.json()["status"] == "success"

    def test_workflow_error_handling(self, client):
        """Test workflow error handling for invalid requests."""
        # Test invalid draft ID - should return error status
        invalid_status_response = client.get("/workflows/invalid-draft-id/status")
        assert invalid_status_response.status_code in [400, 404, 422]

        # Test invalid generation request - should return 404 (ValueError mapped to 404)
        invalid_generate_response = client.post("/workflows/invalid-draft-id/generate", json={
            "sections": ["abstract"]
        })
        assert invalid_generate_response.status_code == 404

        # Test invalid review request - should return 404 (ValueError mapped to 404)
        invalid_review_response = client.post("/workflows/invalid-draft-id/ai-review", json={})
        assert invalid_review_response.status_code == 404


class TestE2EBasicAPISmoke:
    """Smoke tests for basic API functionality."""

    def test_basic_api_endpoints(self, client):
        """Test basic API endpoints still work after workflow integration."""
        # Test ask endpoint
        ask_response = client.get("/ask", params={
            "query_str": "What is virtue ethics?",
            "temperature": 0.3
        })
        assert ask_response.status_code == 200

        # Test get_philosophers endpoint
        philosophers_response = client.get("/get_philosophers")
        assert philosophers_response.status_code == 200
        philosophers_data = philosophers_response.json()
        assert isinstance(philosophers_data, list)

        # Test ask_philosophy endpoint
        philosophy_response = client.post("/ask_philosophy", json={
            "query_str": "What is eudaimonia?",
            "collection": "Aristotle"
        })
        assert philosophy_response.status_code == 200
        philosophy_data = philosophy_response.json()
        assert "text" in philosophy_data

        # Test query_hybrid endpoint
        hybrid_response = client.post("/query_hybrid", json={
            "query_str": "virtue ethics",
            "collection": "Aristotle"
        })
        assert hybrid_response.status_code == 200

    def test_api_parameter_validation(self, client):
        """Test API parameter validation works correctly."""
        # Test temperature bounds
        invalid_temp_response = client.get("/ask", params={
            "query_str": "test",
            "temperature": 1.5  # Invalid: > 1
        })
        assert invalid_temp_response.status_code == 422

        # Test limit bounds
        invalid_limit_response = client.post("/query_hybrid",
            params={"limit": 150},  # Invalid: > 100
            json={"query_str": "test", "collection": "Aristotle"}
        )
        assert invalid_limit_response.status_code == 422

        # Test mutually exclusive parameters
        invalid_modes_response = client.post("/query_hybrid",
            params={"vet_mode": True, "raw_mode": True},
            json={"query_str": "test", "collection": "Aristotle"}
        )
        assert invalid_modes_response.status_code == 400


class TestE2EAuthSmoke:
    """Smoke tests for optional auth functionality."""

    def test_auth_endpoints_when_disabled(self, client):
        """Test auth endpoints work when OAuth is disabled."""
        # Test providers endpoint
        providers_response = client.get("/auth/providers")
        assert providers_response.status_code == 200
        providers_data = providers_response.json()
        assert providers_data["oauth_enabled"] is False

        # Test session creation
        session_response = client.post("/auth/session")
        assert session_response.status_code == 200
        session_data = session_response.json()
        assert "session_id" in session_data
        assert session_data["anonymous"] is True

        # Test auth status
        status_response = client.get("/auth/")
        assert status_response.status_code == 200


class TestE2EWorkflowUtilities:
    """Smoke tests for workflow utility endpoints."""

    def test_workflow_listing(self, client):
        """Test workflow listing functionality."""
        # Create a few drafts
        for i in range(3):
            client.post("/workflows/create", json={
                "title": f"Test Paper {i}",
                "topic": f"Test topic {i}",
                "collection": "Aristotle"
            })

        # Test listing
        list_response = client.get("/workflows/")
        assert list_response.status_code == 200
        list_data = list_response.json()
        assert "drafts" in list_data
        assert len(list_data["drafts"]) >= 3

        # Test with filters
        filtered_response = client.get("/workflows/", params={
            "limit": 2,
            "status_filter": "created"
        })
        assert filtered_response.status_code == 200
        filtered_data = filtered_response.json()
        assert len(filtered_data["drafts"]) <= 2

    def test_workflow_health_check(self, client):
        """Test workflow system health check."""
        health_response = client.get("/workflows/health")
        assert health_response.status_code == 200
        health_data = health_response.json()
        assert health_data["status"] == "healthy"
        assert "workflows" in health_data
        assert "services" in health_data
        assert "features" in health_data