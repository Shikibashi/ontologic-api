# Tests Directory

This directory contains all test files for the Ontologic API.

## Table of Contents

- [Structure](#structure)
- [Test Infrastructure](#test-infrastructure)
- [Running Tests](#running-tests)
- [Test Fixtures](#test-fixtures)
- [Testing Patterns](#testing-patterns)
- [Payment System Tests](#payment-system-tests)
- [Troubleshooting](#troubleshooting)

## Structure

- `integration/` - Integration tests that test complete API endpoints
- `unit/` - Unit tests for individual components and functions
- `performance/` - Performance and load testing scripts
- `helpers/` - Test utilities and helper modules
- `fixtures/` - Test data and fixture generators

## Test Infrastructure

### Fixture Hierarchy

The test suite uses a hierarchical fixture system for resource management:

**Session-Scoped Fixtures** (expensive setup, reused across all tests):
- `base_test_environment`: Standard environment variables for testing
- `sophia_validator`: Validation framework for response quality
- `session_resource_manager`: Resource cleanup coordinator

**Function-Scoped Fixtures** (per-test isolation):
- `test_resource_manager`: Per-test resource cleanup
- `mock_environment`: Isolated environment variables
- `mock_all_services`: Comprehensive service mocking
- `test_client`: FastAPI test client
- `async_client`: Async HTTP client for integration tests

### Helper Modules

- `philosopher_test_mapper.py`: Normalizes philosopher names for consistent testing
- `async_mock_utilities.py`: Utilities for async mock creation
- `database_mock_manager.py`: Database session mocking infrastructure
- `auth_mock_helpers.py`: Authentication and authorization mocking
- `assertions.py`: Custom assertion helpers
- `validators.py`: Response validation utilities

## Integration Tests

The integration tests in this directory provide comprehensive endpoint testing:

- `test_all_endpoints.py` - Basic endpoint testing
- `comprehensive_endpoint_test.py` - Detailed endpoint testing with documentation
- `proper_endpoint_tests.py` - Tests with proper payloads to avoid validation errors
- `final_perfect_tests.py` - Refined tests with correct data formats
- `perfect_100_percent_test.py` - Tests to achieve 100% success rate
- `COMPLETE_100_PERCENT_DOCUMENTATION.py` - Complete documentation of all working endpoints
- `FINAL_100_PERCENT_ACHIEVEMENT.py` - Final verification of 100% success
- `test_auth_endpoints.py` - Authentication-specific testing
- `corrected_endpoint_analysis.py` - Analysis of endpoint behaviors

## Running Tests

### Quick Start

```bash
# Run all tests
pytest

# Run specific test category
pytest -m payment      # Payment tests
pytest -m philosophy   # Philosophy tests
pytest -m auth         # Authentication tests
pytest -m integration  # Integration tests
pytest -m unit         # Unit tests

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=app --cov-report=html
```

### Integration Tests
```bash
# Run all integration tests
python -m pytest tests/integration/

# Run specific test file
python tests/integration/FINAL_100_PERCENT_ACHIEVEMENT.py

# Run with authentication
python tests/integration/test_auth_endpoints.py
```

### Unit Tests
```bash
# Run unit tests
python -m pytest tests/unit/
```

### Performance Tests
```bash
# Run performance tests
python -m pytest tests/performance/
```

## Test Fixtures

### Database Session Mocking

**`mock_db_session`** - Function-scoped database session mock with comprehensive query support:

```python
async def test_database_operation(mock_db_session):
    # Configure query result
    mock_user = MagicMock(id=1, username="testuser")
    mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user

    # Use in code under test
    result = await mock_db_session.execute(select(User).where(User.id == 1))
    user = result.scalar_one_or_none()
    assert user.id == 1
```

**`mock_db_session_factory`** - Creates multiple unique database sessions:

```python
async def test_multiple_sessions(mock_db_session_factory):
    async with mock_db_session_factory() as session1:
        # Use first session
        await session1.execute(...)

    async with mock_db_session_factory() as session2:
        # Use second, independent session
        await session2.execute(...)
```

**`configure_db_query_results`** - Helper for easy result configuration:

```python
def test_user_query(mock_db_session, configure_db_query_results):
    mock_user = MagicMock(id=1, username="testuser")
    configure_db_query_results(mock_db_session, "scalar_one_or_none", mock_user)
    # Query will return mock_user
```

### Authentication Mocking

**`mock_user_free_tier`** - Mock user with free tier subscription:

```python
def test_free_user_access(mock_user_free_tier):
    assert mock_user_free_tier.subscription_tier == SubscriptionTier.FREE
    assert mock_user_free_tier.stripe_customer_id is None
```

**`mock_user_premium_tier`** - Mock user with premium tier:

```python
def test_premium_user_access(mock_user_premium_tier):
    assert mock_user_premium_tier.subscription_tier == SubscriptionTier.PREMIUM
    assert mock_user_premium_tier.stripe_customer_id == "cus_premium123"
```

**`mock_user_admin`** - Mock admin user with superuser privileges:

```python
def test_admin_access(mock_user_admin):
    assert mock_user_admin.is_superuser is True
```

**`mock_auth_token`** - Simple JWT token for testing:

```python
def test_protected_endpoint(test_client, mock_auth_token):
    response = test_client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {mock_auth_token}"}
    )
    assert response.status_code == 200
```

**`make_authenticated_request`** - Helper for authenticated requests:

```python
def test_protected_endpoint(make_authenticated_request):
    response = make_authenticated_request("get", "/users/me")
    assert response.status_code == 200

    # With additional parameters
    response = make_authenticated_request(
        "post",
        "/papers",
        json={"title": "Test Paper"}
    )
```

**`override_auth_dependency`** - Context manager for testing with different users:

```python
def test_with_different_users(override_auth_dependency, mock_user_premium_tier):
    with override_auth_dependency(mock_user_premium_tier):
        response = test_client.get("/premium-feature")
        assert response.status_code == 200
```

**`mock_auth_service_with_user`** - Mocked AuthService:

```python
async def test_with_auth_service(mock_auth_service_with_user):
    user_context = await mock_auth_service_with_user.get_user_context("test_token")
    assert user_context["authenticated"] is True
```

## Testing Patterns

### 1. Testing Async Database Operations

```python
import pytest
from sqlalchemy import select
from app.core.user_models import User

@pytest.mark.asyncio
async def test_user_query(mock_db_session, configure_db_query_results):
    # Setup mock data
    mock_user = User(id=1, username="testuser", email="test@example.com")

    # Configure query result
    result_mock = mock_db_session.execute.return_value
    result_mock.scalar_one_or_none.return_value = mock_user

    # Execute test
    result = await mock_db_session.execute(
        select(User).where(User.id == 1)
    )
    user = result.scalar_one_or_none()

    # Verify
    assert user.id == 1
    assert user.username == "testuser"
```

### 2. Testing Protected Endpoints

```python
def test_admin_only_endpoint(
    test_client,
    override_auth_dependency,
    mock_user_admin
):
    # Test with admin user
    with override_auth_dependency(mock_user_admin):
        response = test_client.get("/admin/users")
        assert response.status_code == 200
```

```python
def test_authentication_required(test_client):
    # Test without authentication
    response = test_client.get("/admin/users")
    assert response.status_code == 401
```

### 3. Testing with Different Subscription Tiers

```python
@pytest.mark.parametrize("user_fixture,expected_status", [
    ("mock_user_free_tier", 403),      # Free tier denied
    ("mock_user_premium_tier", 200),   # Premium tier allowed
    ("mock_user_admin", 200),          # Admin allowed
])
def test_tier_restricted_endpoint(
    test_client,
    override_auth_dependency,
    request,
    user_fixture,
    expected_status
):
    user = request.getfixturevalue(user_fixture)

    with override_auth_dependency(user):
        response = test_client.get("/premium-feature")
        assert response.status_code == expected_status
```

### 4. Testing Philosophy Prompts with Philosopher Mapping

```python
from tests.helpers.philosopher_test_mapper import philosopher_mapper

def test_philosopher_normalization():
    # Various input formats normalize consistently
    assert philosopher_mapper.normalize_philosopher_name("kant") == "Immanuel Kant"
    assert philosopher_mapper.normalize_philosopher_name("Kant") == "Immanuel Kant"
    assert philosopher_mapper.normalize_philosopher_name("Immanuel Kant") == "Immanuel Kant"
```

```python
def test_philosophy_endpoint_with_collection(test_client, mock_all_services):
    # Collection names are normalized automatically
    response = test_client.post(
        "/ask_philosophy",
        json={
            "query_str": "What is truth?",
            "collection": "kant"  # Will be normalized to "Immanuel Kant"
        }
    )
    assert response.status_code == 200
```

### 5. Testing with Mocked Services

```python
def test_endpoint_with_mocked_services(test_client, mock_all_services):
    # Configure mock responses
    mock_llm = mock_all_services["llm"]
    mock_llm.achat.return_value = create_mock_llm_response("Test response")

    mock_qdrant = mock_all_services["qdrant"]
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", "Context text", collection="Aristotle")
    ]

    # Execute request
    response = test_client.post("/ask_philosophy", json={
        "query_str": "Test query",
        "collection": "Aristotle"
    })

    # Verify service calls
    assert response.status_code == 200
    mock_llm.achat.assert_called_once()
    mock_qdrant.gather_points_and_sort.assert_called_once()
```

### 6. Testing Error Handling

```python
def test_validation_error(test_client):
    response = test_client.post("/ask_philosophy", json={
        "invalid_field": "value"  # Missing required fields
    })
    assert response.status_code == 422  # Validation error
    error_detail = response.json()["detail"]
    assert isinstance(error_detail, list)
```

```python
@pytest.mark.asyncio
async def test_service_error_handling(mock_db_session):
    # Configure mock to raise exception
    mock_db_session.execute.side_effect = Exception("Database error")

    # Test that error is handled gracefully
    with pytest.raises(Exception, match="Database error"):
        await mock_db_session.execute(...)
```

### 7. Testing Async Functions

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

```python
@pytest.mark.asyncio
async def test_async_context_manager():
    async with some_async_context() as ctx:
        assert ctx is not None
```

### Best Practices

1. **Use appropriate fixture scopes**: Session for expensive setup, function for test isolation
2. **Clean up resources**: Use `test_resource_manager` to register mocks for automatic cleanup
3. **Use philosopher mapper**: Always normalize philosopher names for consistency
4. **Test both success and failure cases**: Include error handling tests
5. **Use parametrize for similar tests**: Reduce code duplication
6. **Mock external services**: Use `mock_all_services` to avoid real API calls
7. **Test authentication scenarios**: Use `override_auth_dependency` for different user contexts
8. **Keep tests isolated**: Each test should be independent and repeatable

## Test Results

Test results and reports are stored in the `reports/endpoint-testing/` directory.

## Requirements

- Server must be running on `http://localhost:8080`
- Authentication endpoints require valid credentials
- Some tests require specific environment configuration

## Test Fixtures

### Database Mocking

**Available Fixtures:**
- `mock_db_session`: Function-scoped async database session mock
- `mock_db_session_factory`: Factory for creating multiple unique sessions
- `configure_db_query_results`: Helper to configure query return values
- `database_mock_manager`: Comprehensive database mocking infrastructure

**Example Usage:**
```python
async def test_user_query(mock_db_session, configure_db_query_results):
    """Test database query with mocked results."""
    mock_user = MagicMock(id=1, username="testuser")

    # Configure the result
    result_mock = mock_db_session.execute.return_value
    result_mock.scalar_one_or_none.return_value = mock_user

    # Test code here
    result = await mock_db_session.execute(select(User).where(User.id == 1))
    user = result.scalar_one_or_none()

    assert user == mock_user
```

### Authentication Mocking

**Available Fixtures:**
- `mock_auth_token`: Simple JWT token for testing
- `mock_user_free_tier`: User with free subscription tier
- `mock_user_premium_tier`: User with premium subscription
- `mock_user_admin`: Admin user with superuser privileges
- `mock_auth_service_with_user`: Configured AuthService mock
- `make_authenticated_request`: Helper for authenticated API calls
- `override_auth_dependency`: Context manager for auth dependency injection

**Example Usage:**
```python
def test_protected_endpoint(make_authenticated_request):
    """Test endpoint that requires authentication."""
    response = make_authenticated_request("get", "/users/me")
    assert response.status_code == 200

def test_with_different_users(override_auth_dependency, mock_user_premium_tier):
    """Test with specific user context."""
    with override_auth_dependency(mock_user_premium_tier):
        response = test_client.get("/premium-feature")
        assert response.status_code == 200
```

### Service Mocking

**Available Fixtures:**
- `mock_llm_manager`: Mocked LLM service
- `mock_qdrant_manager`: Mocked vector database
- `mock_cache_service`: Mocked caching layer
- `mock_all_services`: Complete service mock suite

**Example Usage:**
```python
def test_philosophy_query(mock_all_services):
    """Test with all services mocked."""
    mock_llm = mock_all_services["llm"]
    mock_qdrant = mock_all_services["qdrant"]

    # Configure mocks
    mock_llm.achat.return_value = create_mock_llm_response("Test response")
    mock_qdrant.gather_points_and_sort.return_value = [
        create_mock_node("node-1", "Context text")
    ]

    # Test code here
```

## Testing Patterns

### Philosophy Prompt Testing

Philosophy tests automatically normalize philosopher names using `philosopher_test_mapper`:

```python
from tests.helpers.philosopher_test_mapper import philosopher_mapper

# All variations map to canonical names
assert philosopher_mapper.normalize_philosopher_name("kant") == "Immanuel Kant"
assert philosopher_mapper.normalize_philosopher_name("Kant") == "Immanuel Kant"
assert philosopher_mapper.normalize_philosopher_name("Immanuel Kant") == "Immanuel Kant"
```

**Collection Parameter Handling:**
- Always use normalized names in test assertions
- `_collection_for_case()` helper automatically normalizes
- Mock node creation uses normalized collection names

### Async Testing

All async tests use `@pytest.mark.asyncio` decorator:

```python
@pytest.mark.asyncio
async def test_async_operation(mock_db_session):
    """Test asynchronous database operation."""
    # Configure mock
    mock_db_session.execute.return_value.scalar_one.return_value = mock_data

    # Test async operation
    result = await database_operation()

    assert result == expected_value
```

### Test Isolation

Tests are automatically isolated using:
- Function-scoped fixtures (new instances per test)
- `test_resource_manager` for automatic cleanup
- `mock_environment` for environment variable isolation
- `TestEnvironmentManager` for parallel test safety

### Response Validation

Use assertion helpers for consistent validation:

```python
from tests.conftest import (
    assert_philosophy_response_valid,
    assert_response_schema,
    assert_keywords_present
)

def test_response_quality(test_client):
    response = test_client.post("/ask_philosophy", json=payload)
    payload = response.json()

    # Validate structure
    assert_philosophy_response_valid(prompt_id, payload)

    # Validate schema
    assert_response_schema(payload, ["text", "raw", "metadata"])

    # Validate content
    assert_keywords_present(payload["text"], ["philosophy", "ethics"])
```

### Best Practices

1. **Use Existing Fixtures**: Leverage `conftest.py` fixtures instead of creating mocks inline
2. **Normalize Names**: Always use `philosopher_mapper` for philosopher names
3. **Clean Async Patterns**: Use `AsyncMock` for async methods, register with resource manager
4. **Defensive Validation**: Check for None/optional fields in response validation
5. **Isolated Tests**: Each test should be independent and idempotent

## Payment System Tests

The payment system has multiple test levels:

### Smoke Tests (No Stripe Keys Required)

Quick validation that payment components are installed and importable:

```bash
# Run payment smoke tests
uv run pytest tests/test_payment_smoke.py -v

# Run all smoke tests
uv run pytest -m smoke
```

These tests verify:
- Stripe package is installed
- Payment models can be imported
- Payment services can be instantiated
- Payment routers are configured
- Configuration has payment settings

### Integration Tests (Mocked Stripe)

Tests that verify payment service logic with mocked Stripe calls:

```bash
# Run payment integration tests
uv run pytest tests/test_payment_system_integration.py -v

# Run all payment tests
uv run pytest -m payment
```

These tests use mocked Stripe API calls and don't require real API keys.

### Live Endpoint Tests (Optional)

Tests that verify payment endpoints with a running server:

```bash
# Enable live payment endpoint tests
RUN_LIVE_PAYMENT_TESTS=1 uv run pytest tests/test_payment_endpoints_live.py -v
```

These tests are skipped by default. They verify:
- Endpoint paths are correct
- Authentication is required
- Request/response schemas match

### Full Payment Integration Tests (Requires Stripe Test Keys)

Complete end-to-end payment flow tests:

```bash
# Set up Stripe test keys
export APP_STRIPE_SECRET_KEY=sk_test_...
export APP_STRIPE_PUBLISHABLE_KEY=pk_test_...
export APP_PAYMENTS_ENABLED=true

# Run full integration tests
uv run pytest tests/test_payment_integration.py -v
```

These tests require:
- Stripe test API keys from https://dashboard.stripe.com/test/apikeys
- Running database
- Payment system enabled in configuration

## Payment Test Fixtures

Available fixtures for payment testing (defined in `conftest.py`):

- `payment_settings`: Settings with payments enabled
- `mock_payment_service`: Mocked PaymentService
- `mock_subscription_manager`: Mocked SubscriptionManager
- `mock_billing_service`: Mocked BillingService
- `mock_stripe_customer`: Mock Stripe customer object
- `mock_stripe_subscription`: Mock Stripe subscription object
- `mock_stripe_checkout_session`: Mock Stripe checkout session

## Troubleshooting Payment Tests

### "Stripe library not installed"

```bash
uv sync  # Install all dependencies including Stripe
```

### "Payments not enabled in configuration"

Check `app/config/toml/dev.toml`:
```toml
[payments]
enabled = true
```

### "Stripe keys not configured"

For tests that require real Stripe API:
1. Get test keys from https://dashboard.stripe.com/test/apikeys
2. Create `.env` file (copy from `.env.example`)
3. Add keys to `.env`:
   ```
   APP_STRIPE_SECRET_KEY=sk_test_...
   APP_STRIPE_PUBLISHABLE_KEY=pk_test_...
   ```

### Tests fail with "404 Not Found" on payment endpoints

Payment routes are only registered when `payments_enabled=true`. Check:
1. Configuration: `app/config/toml/dev.toml`
2. Environment: `APP_PAYMENTS_ENABLED=true`
3. Server logs for "PaymentService initialized"