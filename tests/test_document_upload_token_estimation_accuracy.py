import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_document_upload_token_estimation_accuracy(authenticated_client, test_user):
    """
    Verify that document upload token estimation is accurate.
    """
    # Create a 1000-character test document
    file_content = "X" * 1000

    # Upload document
    response = authenticated_client.post(
        "/documents/upload",
        files={"file": ("test.txt", file_content, "text/plain")}
    )

    assert response.status_code == 201

    # Get user usage stats
    usage_response = authenticated_client.get("/users/me/usage")
    usage = usage_response.json()

    # Expected tokens: 1000 chars / 4 chars per token = 250 tokens
    expected_tokens = 1000 // 4
    actual_tokens = usage["tokens_used"]

    # Allow 10% margin of error
    assert abs(actual_tokens - expected_tokens) < (expected_tokens * 0.1), \
        f"Token estimation off by {abs(actual_tokens - expected_tokens)} tokens"
