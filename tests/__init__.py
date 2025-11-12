"""Test suite for Ontologic Philosophy API.

This package contains comprehensive tests for:
- API endpoints (/ask, /ask_philosophy, /query_hybrid)
- Philosophy prompt responses (37 test cases)
- Service layer (LLMManager, QdrantManager)
- Workflow functionality
- Integration tests

Test Organization:
- conftest.py: Shared fixtures and utilities
- fixtures/: Canned responses and test data
- helpers/: Assertion and validation utilities
- test_ask_philosophy_prompts.py: Philosophy prompt regression tests
- test_ask_and_query_endpoints.py: Endpoint coverage tests
- test_e2e_smoke.py: End-to-end smoke tests
- test_refeed.py: Refeed functionality tests
- test_endpoints_refeed.py: Refeed endpoint tests
"""

__version__ = "1.0.0"
