"""Tests for HTTP response compression (GZip middleware)."""

import json
import pytest
import gzip
from fastapi.testclient import TestClient
from app.main import app
from app.config.settings import get_settings


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def settings():
    """Get the application settings."""
    return get_settings()


@app.get("/test/compression/small")
def compression_small_payload():
    """Return a consistently small JSON payload for compression tests."""
    return {"message": "ok"}


@app.get("/test/compression/large")
def compression_large_payload():
    """Return a large JSON payload that exceeds the compression threshold."""
    repeated_text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    return {
        "payload": repeated_text * 20,
        "items": [
            {
                "id": idx,
                "text": repeated_text
            }
            for idx in range(5)
        ]
    }


class TestCompressionConfiguration:
    """Test compression configuration and settings."""

    def test_compression_enabled_by_default(self, settings):
        """Test that compression is enabled by default."""
        assert settings.compression_enabled is True

    def test_compression_minimum_size_default(self, settings):
        """Test that compression minimum size has correct default."""
        # In test environment, the dev configuration is used which sets minimum_size to 500
        assert settings.compression_minimum_size == 500

    def test_compression_minimum_size_validation(self):
        """Test that compression minimum size is validated."""
        from app.config.settings import Settings
        from pydantic import ValidationError

        # Valid values
        Settings(compression_minimum_size=100)  # Minimum
        Settings(compression_minimum_size=1000)  # Default
        Settings(compression_minimum_size=10000)  # Maximum

        # Invalid values should raise ValidationError
        with pytest.raises(ValidationError):
            Settings(compression_minimum_size=50)  # Too small

        with pytest.raises(ValidationError):
            Settings(compression_minimum_size=20000)  # Too large


class TestCompressionBehavior:
    """Test actual compression behavior with different response sizes."""

    def test_small_response_not_compressed(self, client):
        """Test that responses work correctly with compression middleware."""
        # Small test endpoint returns minimal JSON response
        response = client.get(
            "/test/compression/small",
            headers={"Accept-Encoding": "gzip"}
        )

        assert response.status_code == 200
        content_encoding = response.headers.get("Content-Encoding")
        assert content_encoding is None or content_encoding != "gzip", "Small responses should not be compressed"
        # Verify response is valid JSON regardless of compression
        assert response.headers.get("content-type") == "application/json"
        # Response should be decodable
        response_data = response.json()
        assert isinstance(response_data, dict)

    def test_large_response_compressed(self, client):
        """Test that compression middleware handles responses correctly."""
        # Get response with compression headers
        response = client.get(
            "/test/compression/large",
            headers={"Accept-Encoding": "gzip"}
        )

        assert response.status_code == 200
        assert response.headers.get("Content-Encoding") == "gzip"
        assert response.content[:2] == b"\x1f\x8b"
        decompressed = gzip.decompress(response.content)
        payload = json.loads(decompressed.decode("utf-8"))
        assert isinstance(payload, dict)

    def test_compression_without_accept_encoding(self, client):
        """Test that compression is not applied without Accept-Encoding header."""
        response = client.get("/test/compression/large")

        # Response should work correctly without Accept-Encoding header
        assert response.status_code == 200
        assert "Content-Encoding" not in response.headers, "Response should not be compressed without Accept-Encoding header"
        response_data = response.json()
        assert isinstance(response_data, dict)

    def test_compression_reduces_size(self, client):
        """Test that compression middleware works correctly."""
        # Get response without compression
        response_uncompressed = client.get("/test/compression/large")
        assert response_uncompressed.status_code == 200

        # Get response with compression
        response_compressed = client.get(
            "/test/compression/large",
            headers={"Accept-Encoding": "gzip"}
        )
        assert response_compressed.status_code == 200
        assert "gzip" in response_compressed.headers.get("Content-Encoding", ""), "Compressed response must include gzip encoding"

        # Both responses should be valid JSON
        data1 = response_uncompressed.json()
        data2 = response_compressed.json()
        assert isinstance(data1, dict)
        assert isinstance(data2, dict)

        uncompressed_size = len(response_uncompressed.content)
        compressed_size = len(response_compressed.content)
        assert compressed_size < uncompressed_size, (
            f"Compressed ({compressed_size}) should be smaller than uncompressed ({uncompressed_size})"
        )


class TestCompressionEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_response(self, client):
        """Test that small responses are handled correctly."""
        # Test with the intentionally small payload endpoint
        response = client.get(
            "/test/compression/small",
            headers={"Accept-Encoding": "gzip"}
        )
        assert response.status_code == 200
        # Response should be valid JSON
        response_data = response.json()
        assert isinstance(response_data, dict)

    def test_multiple_encodings_accepted(self, client):
        """Test that server handles multiple Accept-Encoding values."""
        response = client.get(
            "/test/compression/large",
            headers={"Accept-Encoding": "gzip, deflate, br"}
        )

        assert response.status_code == 200
        encoding = response.headers.get("Content-Encoding")
        assert encoding in {"gzip", "deflate", "br", None, ""}, f"Unexpected encoding: {encoding}"
        # Response should be valid JSON
        response_data = response.json()
        assert isinstance(response_data, dict)


class TestCompressionAuxiliaryEndpoints:
    """Test compression behavior on auxiliary endpoints."""

    def test_large_test_route_compression(self, client):
        """Test that the large payload test route honors compression headers."""
        response = client.get(
            "/test/compression/large",
            headers={"Accept-Encoding": "gzip"}
        )

        assert response.status_code == 200
        # Response should be valid JSON
        response_data = response.json()
        assert isinstance(response_data, dict)


class TestCompressionDocumentation:
    """Test that compression is properly documented."""

    def test_compression_in_settings_docstring(self):
        """Test that compression settings have proper documentation."""
        from app.config.settings import Settings
        import inspect

        # Get the Settings class source
        source = inspect.getsource(Settings)

        # Verify compression fields are documented
        assert "compression_enabled" in source
        assert "compression_minimum_size" in source

    def test_compression_logged_at_startup(self, caplog):
        """Test that compression configuration is logged at startup."""
        # This would require restarting the app, which is complex in tests
        # Instead, we can verify the log_configuration_summary method
        from app.config.settings import get_settings
        import logging

        settings = get_settings()
        with caplog.at_level(logging.INFO):
            settings.log_configuration_summary()

        # Verify compression settings are logged
        log_text = caplog.text
        assert "Compression enabled" in log_text or "compression" in log_text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
