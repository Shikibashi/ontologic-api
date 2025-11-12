"""Positive-path tests for workflow endpoints using dependency overrides."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.core import dependencies as deps


def test_create_draft_success(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.create_draft = AsyncMock(return_value="draft-123")

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    with patch("app.router.workflows.workflow_validator.validate_paper_creation", return_value=None):
        response = test_client.post(
            "/workflows/create",
            json={
                "title": "Metaethics essay",
                "topic": "Intuitionism",
                "collection": "Metaethics",
                "immersive_mode": True,
                "temperature": 0.2,
                "metadata": {"course": "PHIL201"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_id"] == "draft-123"
    assert payload["status"] == "created"
    mock_workflow.create_draft.assert_called_once()


def test_generate_sections_success(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.generate_sections = AsyncMock(return_value={
        "draft_id": "draft-123",
        "sections_generated": ["introduction"],
        "sections_failed": [],
        "total_sections": 1,
        "final_status": "completed",
    })

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    response = test_client.post(
        "/workflows/draft-123/generate",
        json={"sections": ["introduction"], "use_expansion": True, "expansion_methods": ["hyde"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections_generated"] == ["introduction"]
    mock_workflow.generate_sections.assert_called_once()


def test_ai_review_success(test_client, override_workflow_deps):
    mock_review_workflow = MagicMock()
    mock_review_workflow.review_draft = AsyncMock(return_value={
        "draft_id": "draft-123",
        "review_id": "review-1",
        "status": "completed",
        "summary": {"strengths": 2, "improvements": 1},
        "blocking_issues": 0,
        "verification_coverage": "high",
    })

    override_workflow_deps({deps.get_review_workflow: lambda: mock_review_workflow})

    response = test_client.post(
        "/workflows/draft-123/ai-review",
        json={
            "rubric": ["accuracy"],
            "severity_gate": "low",
            "max_evidence_per_question": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_id"] == "review-1"
    mock_review_workflow.review_draft.assert_called_once()


def test_apply_suggestions_success(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.apply_suggestions = AsyncMock(return_value={
        "draft_id": "draft-123",
        "suggestions_applied": 3,
        "status": "updated",
    })

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    response = test_client.post(
        "/workflows/draft-123/apply",
        json={"accept_all": False, "accept_sections": ["introduction"], "suggestion_ids": ["s-1"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "updated"
    mock_workflow.apply_suggestions.assert_called_once()


def test_get_review_data_success(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.get_draft_status = AsyncMock(return_value={"draft_id": "draft-123"})

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    draft_mock = MagicMock()
    draft_mock.review_data = {"reviewed_at": "2024-01-01"}
    draft_mock.suggestions = [{"id": "s-1", "blocking": False}]

    with patch("app.services.paper_service.PaperDraftService.get_draft", return_value=draft_mock):
        response = test_client.get("/workflows/draft-123/review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft_id"] == "draft-123"
    assert payload["review_summary"]["total_suggestions"] == 1
    mock_workflow.get_draft_status.assert_called_once()
