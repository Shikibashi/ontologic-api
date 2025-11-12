"""Regression tests for HTTPException propagation in /workflows endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.core import dependencies as deps


def test_create_draft_propagates_http_exception(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.create_draft.side_effect = HTTPException(status_code=409, detail="draft exists")

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    with patch("app.router.workflows.workflow_validator.validate_paper_creation", return_value=None):
        response = test_client.post(
            "/workflows/create",
            json={
                "title": "Test",
                "topic": "Virtue ethics",
                "collection": "Aristotle",
                "immersive_mode": False,
                "temperature": 0.3,
                "metadata": None,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "draft exists"


def test_generate_sections_propagates_http_exception(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.generate_sections.side_effect = HTTPException(status_code=423, detail="draft locked")

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    response = test_client.post(
        "/workflows/test-draft/generate",
        json={"sections": ["introduction"], "use_expansion": False, "expansion_methods": None},
    )

    assert response.status_code == 423
    assert response.json()["detail"] == "draft locked"


def test_ai_review_propagates_http_exception(test_client, override_workflow_deps):
    mock_review_workflow = MagicMock()
    mock_review_workflow.review_draft.side_effect = HTTPException(status_code=451, detail="review unavailable")

    override_workflow_deps({deps.get_review_workflow: lambda: mock_review_workflow})

    response = test_client.post(
        "/workflows/test-draft/ai-review",
        json={
            "rubric": ["accuracy"],
            "severity_gate": "medium",
            "max_evidence_per_question": 3,
        },
    )

    assert response.status_code == 451
    assert response.json()["detail"] == "review unavailable"


def test_apply_suggestions_propagates_http_exception(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.apply_suggestions.side_effect = HTTPException(status_code=412, detail="missing review")

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    response = test_client.post(
        "/workflows/test-draft/apply",
        json={"accept_all": True},
    )

    assert response.status_code == 412
    assert response.json()["detail"] == "missing review"


def test_get_review_data_propagates_http_exception(test_client, override_workflow_deps):
    mock_workflow = MagicMock()
    mock_workflow.get_draft_status.side_effect = HTTPException(status_code=410, detail="draft archived")

    override_workflow_deps({deps.get_paper_workflow: lambda: mock_workflow})

    response = test_client.get("/workflows/test-draft/review")

    assert response.status_code == 410
    assert response.json()["detail"] == "draft archived"


def test_list_drafts_propagates_http_exception(test_client):
    with patch("app.services.paper_service.PaperDraftService.list_drafts", side_effect=HTTPException(status_code=502, detail="db down")):
        response = test_client.get("/workflows")

    assert response.status_code == 502
    assert response.json()["detail"] == "db down"
