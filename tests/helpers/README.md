# Enhanced Mocking Framework

This directory contains the enhanced mocking framework for comprehensive service mocking with async-aware capabilities and proper lifecycle management.

## Components

### ServiceMockManager (`test_mock_manager.py`)
Comprehensive service mocking manager that creates mocks for all services with proper async handling and resource cleanup.

**Key Features:**
- Creates mocks for all services (chat, payment, auth, cache, etc.)
- Proper async method mocking with AsyncMock
- Resource tracking and cleanup
- Correct attribute access patterns (e.g., `cache_service` not `_cache_service`)

**Usage:**
```python
from tests.helpers.test_mock_manager import ServiceMockManager

manager = ServiceMockManager()
services = manager.create_all_service_mocks()
# Use services["chat_history"], services["payment"], etc.
```

### AsyncMockUtilities (`async_mock_utilities.py`)
Utilities for creating async-aware mocks with proper lifecycle management.

**Key Features:**
- Async service mock creation
- Async context manager mocks
- Async generator mocks
- Session lifecycle management

**Usage:**
```python
from tests.helpers.async_mock_utilities import AsyncMockUtilities

utils = AsyncMockUtilities()
mock = utils.create_async_service_mock(MyService)
```

### DatabaseMockManager (`database_mock_manager.py`)
Database session mock management with proper SQLAlchemy method signatures and transaction handling.

**Key Features:**
- AsyncSession mocks with proper method signatures
- Transaction rollback simulation
- Query result mocking
- SQLAlchemy Result and ScalarResult mocks

**Usage:**
```python
from tests.helpers.database_mock_manager import DatabaseMockManager

db_manager = DatabaseMockManager()
session_mock = db_manager.create_async_session_mock()
db_manager.configure_query_results("session_id", "scalar", "result")
```

### AuthMockHelper (`auth_mock_helpers.py`)
Authentication and authorization mock helpers for comprehensive auth testing.

**Key Features:**
- JWT token generation for different user types
- User object creation (admin, premium, regular)
- Authentication context creation
- Auth dependency patching

**Usage:**
```python
from tests.helpers.auth_mock_helpers import AuthMockHelper, create_test_auth_context

# Create auth context for testing
admin_context = create_test_auth_context("admin")
user = admin_context["user"]
headers = admin_context["headers"]
```

## Integration with conftest.py

The framework is integrated into `conftest.py` with the following fixtures:

- `service_mock_manager`: Function-scoped ServiceMockManager
- `database_mock_manager`: Function-scoped DatabaseMockManager  
- `auth_mock_helper`: Function-scoped AuthMockHelper
- `comprehensive_service_mocks`: All service mocks pre-configured

## Usage in Tests

### Basic Service Mocking
```python
def test_my_feature(comprehensive_service_mocks):
    services = comprehensive_service_mocks
    
    # Use mocked services
    result = await services["chat_history"].store_message(...)
    assert result is not None
```

### Database Testing
```python
def test_database_operations(database_mock_manager):
    session_mock = database_mock_manager.create_async_session_mock()
    database_mock_manager.configure_query_results("default", "scalar", my_result)
    
    # Use session_mock in your test
```

### Authentication Testing
```python
def test_authenticated_endpoint(auth_mock_helper):
    admin_context = create_test_auth_context("admin")
    
    # Use admin_context["headers"] for authenticated requests
    response = client.get("/admin/endpoint", headers=admin_context["headers"])
```

## Key Improvements Over Previous Mocking

1. **Correct Attribute Access**: Payment service uses `cache_service` not `_cache_service`
2. **No Non-existent Methods**: Removed references to `_get_or_create_customer`
3. **Proper Async Handling**: All async methods use AsyncMock consistently
4. **Comprehensive Coverage**: Mocks for all services with realistic behavior
5. **Resource Management**: Proper cleanup and lifecycle management
6. **Authentication Support**: Complete auth mocking with JWT tokens and user roles

## Testing the Framework

Run the integration test to verify all components work:

```bash
uv run pytest tests/test_mocking_framework_integration.py -v
```

This test verifies that all mocking components work together and can be used in actual test scenarios.