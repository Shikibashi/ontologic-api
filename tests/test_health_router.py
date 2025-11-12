"""Tests for health router covering healthy/unhealthy scenarios."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


def test_health_check_healthy(test_client):
    healthy = AsyncMock(return_value={"status": "healthy"})
    with patch("app.router.health.check_database_health", healthy), \
         patch("app.router.health.check_qdrant_health", healthy), \
         patch("app.router.health.check_redis_health", healthy), \
         patch("app.router.health.check_llm_health", healthy):
        response = test_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"


def test_health_check_unhealthy_sets_503(test_client):
    healthy = AsyncMock(return_value={"status": "healthy"})
    degraded = AsyncMock(return_value={"status": "unhealthy", "message": "db down"})

    with patch("app.router.health.check_database_health", degraded), \
         patch("app.router.health.check_qdrant_health", healthy), \
         patch("app.router.health.check_redis_health", healthy), \
         patch("app.router.health.check_llm_health", healthy):
        response = test_client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["services"]["database"]["message"] == "db down"


def test_health_check_exception_handled(test_client):
    error = AsyncMock(side_effect=RuntimeError("boom"))
    healthy = AsyncMock(return_value={"status": "healthy"})

    with patch("app.router.health.check_database_health", error), \
         patch("app.router.health.check_qdrant_health", healthy), \
         patch("app.router.health.check_redis_health", healthy), \
         patch("app.router.health.check_llm_health", healthy):
        response = test_client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["services"]["database"]["status"] == "error"
    assert payload["services"]["database"]["message"] == "boom"


def test_readiness_check_ready(test_client):
    healthy = AsyncMock(return_value={"status": "healthy"})
    with patch("app.router.health.check_database_health", healthy), \
         patch("app.router.health.check_qdrant_health", healthy), \
         patch("app.router.health.check_llm_health", healthy):
        response = test_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_check_unready(test_client):
    unhealthy = AsyncMock(return_value={"status": "unhealthy"})
    healthy = AsyncMock(return_value={"status": "healthy"})

    with patch("app.router.health.check_database_health", unhealthy), \
         patch("app.router.health.check_qdrant_health", healthy), \
         patch("app.router.health.check_llm_health", healthy):
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not ready"


def test_readiness_check_unexpected_exception(test_client):
    with patch("asyncio.gather", side_effect=RuntimeError("boom")):
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not ready"
    assert payload["error"] == "boom"


def test_liveness_check(test_client):
    response = test_client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"
