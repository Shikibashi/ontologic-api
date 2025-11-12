"""Test HTTP error guard decorator."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.http_error_guard import http_error_guard
from app.core.exceptions import LLMTimeoutError, ValidationError, DatabaseError

# Create test app
app = FastAPI()

@app.get("/timeout")
@http_error_guard
async def timeout_endpoint():
    raise LLMTimeoutError("Request timed out")

@app.get("/validation")
@http_error_guard
async def validation_endpoint():
    raise ValidationError("Invalid input")

@app.get("/database")
@http_error_guard
async def database_endpoint():
    raise DatabaseError("Database connection failed")

@app.get("/success")
@http_error_guard
async def success_endpoint():
    return {"status": "ok"}

def test_timeout_error():
    """Test LLM timeout error mapping."""
    client = TestClient(app)
    response = client.get("/timeout")
    assert response.status_code == 504
    assert "timeout" in response.json()["detail"].lower()

def test_validation_error():
    """Test validation error mapping."""
    client = TestClient(app)
    response = client.get("/validation")
    assert response.status_code == 422
    assert "Invalid input" in response.json()["detail"]

def test_database_error():
    """Test database error mapping."""
    client = TestClient(app)
    response = client.get("/database")
    assert response.status_code == 500
    assert "Database error" in response.json()["detail"]

def test_success_response():
    """Test successful response passes through."""
    client = TestClient(app)
    response = client.get("/success")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"