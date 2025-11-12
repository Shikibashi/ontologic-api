"""Shared pytest fixtures and utilities for philosophy API tests."""

from __future__ import annotations

# Set test environment before any imports
import os
os.environ["APP_ENV"] = "test"

import asyncio
import inspect
import tempfile
import threading
import time
import weakref
from contextlib import asynccontextmanager
from typing import Any, Dict, Iterable, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures import get_canned_response
from tests.helpers import (
    assert_ask_response_valid as _helper_assert_ask_response_valid,
    assert_hybrid_query_response_valid as _helper_assert_hybrid_query_response_valid,
    assert_keywords_present as _helper_assert_keywords_present,
    assert_philosophy_response_valid as _helper_assert_philosophy_response_valid,
    assert_response_schema as _helper_assert_response_schema,
)
from tests.helpers.factories import (
    create_conversation_history as _factory_create_conversation_history,
    create_mock_llm_response as _factory_create_mock_llm_response,
    create_mock_node as _factory_create_mock_node,
    create_mock_nodes_dict as _factory_create_mock_nodes_dict,
)
from tests.helpers.philosopher_test_mapper import philosopher_mapper
from tests.helpers.test_philosopher_selection import (
    select_test_philosopher,
    get_philosophers_for_category,
    test_philosopher_selector
)
from tests.helpers.test_mock_manager import ServiceMockManager
from tests.helpers.async_mock_utilities import (
    AsyncMockUtilities, AsyncSessionLifecycleManager, AsyncResourceManager,
    create_async_service_mock_with_lifecycle, create_database_session_mock_with_queries
)
from tests.helpers.database_mock_manager import DatabaseMockManager, create_test_database_session
from tests.helpers.auth_mock_helpers import AuthMockHelper, create_test_auth_context


# ---------------------------------------------------------------------------
# Test Resource Management
# ---------------------------------------------------------------------------


class TestResourceManager:
    """Manages test resources and ensures proper cleanup with performance optimizations."""
    
    def __init__(self):
        self.active_mocks: Dict[str, MagicMock] = {}
        self.temp_files: List[str] = []
        self.async_resources: Set[Any] = set()
        self._cleanup_callbacks: List[callable] = []
        self._mock_pool: Dict[str, List[MagicMock]] = {}  # Pool for mock reuse
        self._resource_cache: Dict[str, Any] = {}  # Cache for expensive resources
    
    def register_mock(self, name: str, mock: MagicMock) -> MagicMock:
        """Register a mock for cleanup tracking."""
        self.active_mocks[name] = mock
        return mock
    
    def get_or_create_mock(self, mock_type: str, factory_func: callable) -> MagicMock:
        """Get a mock from the pool or create a new one for reuse."""
        if mock_type not in self._mock_pool:
            self._mock_pool[mock_type] = []
        
        # Try to reuse an existing mock
        if self._mock_pool[mock_type]:
            mock = self._mock_pool[mock_type].pop()
            mock.reset_mock()  # Reset state for reuse
            return mock
        
        # Create new mock if none available
        mock = factory_func()
        return mock
    
    def return_mock_to_pool(self, mock_type: str, mock: MagicMock) -> None:
        """Return a mock to the pool for reuse."""
        if mock_type not in self._mock_pool:
            self._mock_pool[mock_type] = []
        
        # Reset the mock and return to pool
        mock.reset_mock()
        self._mock_pool[mock_type].append(mock)
    
    def cache_resource(self, key: str, resource: Any) -> Any:
        """Cache an expensive resource for reuse."""
        self._resource_cache[key] = resource
        return resource
    
    def get_cached_resource(self, key: str) -> Optional[Any]:
        """Get a cached resource."""
        return self._resource_cache.get(key)
    
    def register_temp_file(self, filepath: str) -> str:
        """Register a temporary file for cleanup."""
        self.temp_files.append(filepath)
        return filepath
    
    def register_async_resource(self, resource: Any) -> Any:
        """Register an async resource for cleanup."""
        self.async_resources.add(resource)
        return resource
    
    def add_cleanup_callback(self, callback: callable) -> None:
        """Add a cleanup callback to be executed during teardown."""
        self._cleanup_callbacks.append(callback)
    
    async def cleanup_all(self) -> None:
        """Cleanup all registered resources."""
        # Execute cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                # Log but don't fail tests due to cleanup issues
                print(f"Warning: Cleanup callback failed: {e}")
        
        # Reset mocks (optimized to avoid unnecessary resets)
        for name, mock in self.active_mocks.items():
            try:
                if hasattr(mock, 'call_count') and mock.call_count > 0:
                    mock.reset_mock()
            except Exception:
                pass
        
        # Close async resources
        for resource in self.async_resources.copy():
            try:
                if hasattr(resource, 'close'):
                    if asyncio.iscoroutinefunction(resource.close):
                        await resource.close()
                    else:
                        resource.close()
            except Exception:
                pass
        
        # Clean up temp files
        import os
        for filepath in self.temp_files:
            try:
                if os.path.exists(filepath):
                    os.unlink(filepath)
            except Exception:
                pass
        
        # Clear all collections (keep mock pool and resource cache for reuse)
        self.active_mocks.clear()
        self.temp_files.clear()
        self.async_resources.clear()
        self._cleanup_callbacks.clear()
        # Note: _mock_pool and _resource_cache are kept for performance


# Global resource manager for session-scoped cleanup
_session_resource_manager = TestResourceManager()


# ---------------------------------------------------------------------------
# Test Environment Standardization Utilities
# ---------------------------------------------------------------------------


class TestEnvironmentManager:
    """Manages consistent test environment setup and state cleanup with parallel execution safety."""
    
    _test_isolation_lock = asyncio.Lock()
    _active_tests: Set[str] = set()
    _test_resources: Dict[str, Any] = {}
    
    @staticmethod
    def get_test_database_url(test_name: str = "default") -> str:
        """Generate isolated test database URL for a specific test."""
        import tempfile
        import os
        import threading
        
        # Use thread ID and process ID for unique database names
        thread_id = threading.get_ident()
        process_id = os.getpid()
        temp_dir = tempfile.gettempdir()
        db_name = f"test_{test_name}_{process_id}_{thread_id}_{hash(test_name) % 10000}.db"
        return f"sqlite:///{os.path.join(temp_dir, db_name)}"
    
    @staticmethod
    def get_standard_test_env() -> Dict[str, str]:
        """Get standardized environment variables for testing."""
        return {
            "APP_ENV": "test",
            "LOG_LEVEL": "ERROR",
            "QDRANT_API_KEY": "test-api-key",
            "QDRANT_URL": "http://localhost:6333",
            "PAYMENTS_ENABLED": "false",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_standardized",
            "STRIPE_SECRET_KEY": "sk_test_standardized", 
            "STRIPE_WEBHOOK_SECRET": "whsec_test_standardized",
            "REDIS_URL": "redis://localhost:6379/15",  # Use test DB 15
            "CACHE_ENABLED": "false",
            "TELEMETRY_ENABLED": "false",
            "TRACING_ENABLED": "false",
            "RATE_LIMITING_ENABLED": "false",
        }
    
    @staticmethod
    async def cleanup_test_state(test_name: str = None):
        """Clean up test state and reset global variables with parallel safety."""
        async with TestEnvironmentManager._test_isolation_lock:
            # Remove test from active set
            if test_name and test_name in TestEnvironmentManager._active_tests:
                TestEnvironmentManager._active_tests.remove(test_name)
            
            # Clear any cached singletons
            try:
                from app.core.dependencies import reset_dependency_cache
                reset_dependency_cache()
            except ImportError:
                pass
            
            # Clear test-specific resources
            if test_name and test_name in TestEnvironmentManager._test_resources:
                resources = TestEnvironmentManager._test_resources.pop(test_name)
                for resource in resources:
                    try:
                        if hasattr(resource, 'close'):
                            if asyncio.iscoroutinefunction(resource.close):
                                await resource.close()
                            else:
                                resource.close()
                    except Exception:
                        pass
    
    @staticmethod
    async def ensure_test_isolation(test_name: str = None):
        """Ensure proper test isolation by resetting shared state with parallel safety."""
        async with TestEnvironmentManager._test_isolation_lock:
            # Add test to active set
            if test_name:
                TestEnvironmentManager._active_tests.add(test_name)
                if test_name not in TestEnvironmentManager._test_resources:
                    TestEnvironmentManager._test_resources[test_name] = []
            
            # Reset any module-level caches or singletons
            import sys
            
            # Clear specific modules that might have cached state
            modules_to_reset = [
                'app.services.llm_manager',
                'app.services.qdrant_manager', 
                'app.services.cache_service',
                'app.core.dependencies'
            ]
            
            for module_name in modules_to_reset:
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                    # Reset any module-level variables that might cache state
                    if hasattr(module, '_instance'):
                        module._instance = None
                    if hasattr(module, '_cached_manager'):
                        module._cached_manager = None
    
    @staticmethod
    def register_test_resource(test_name: str, resource: Any):
        """Register a resource for a specific test for cleanup."""
        if test_name not in TestEnvironmentManager._test_resources:
            TestEnvironmentManager._test_resources[test_name] = []
        TestEnvironmentManager._test_resources[test_name].append(resource)
    
    @staticmethod
    def get_active_tests() -> Set[str]:
        """Get the set of currently active tests."""
        return TestEnvironmentManager._active_tests.copy()


def create_isolated_test_environment(test_name: str) -> Dict[str, str]:
    """Create an isolated test environment for a specific test."""
    env_manager = TestEnvironmentManager()
    base_env = env_manager.get_standard_test_env()
    base_env["ONTOLOGIC_DB_URL"] = env_manager.get_test_database_url(test_name)
    return base_env


def setup_test_state_cleanup(resource_manager: TestResourceManager, test_name: str = None):
    """Setup comprehensive test state cleanup with parallel safety."""
    async def cleanup_callback():
        await TestEnvironmentManager.cleanup_test_state(test_name)
        await TestEnvironmentManager.ensure_test_isolation(test_name)
    
    resource_manager.add_cleanup_callback(cleanup_callback)


class TestHealthMonitor:
    """Monitor test health and detect issues that could affect reliability."""
    
    def __init__(self):
        self.test_failures: Dict[str, int] = {}
        self.test_durations: Dict[str, List[float]] = {}
        self.resource_usage: Dict[str, Dict[str, float]] = {}
        self.parallel_conflicts: List[Dict[str, Any]] = []
    
    def record_test_result(self, test_name: str, passed: bool, duration: float, memory_usage: float):
        """Record test execution results for health monitoring."""
        if not passed:
            self.test_failures[test_name] = self.test_failures.get(test_name, 0) + 1
        
        if test_name not in self.test_durations:
            self.test_durations[test_name] = []
        self.test_durations[test_name].append(duration)
        
        self.resource_usage[test_name] = {
            'duration': duration,
            'memory': memory_usage,
            'timestamp': time.time()
        }
    
    def detect_flaky_tests(self, failure_threshold: int = 3) -> List[str]:
        """Detect tests that fail intermittently."""
        return [test for test, failures in self.test_failures.items() if failures >= failure_threshold]
    
    def detect_slow_tests(self, duration_threshold: float = 5.0) -> List[str]:
        """Detect tests that are consistently slow."""
        slow_tests = []
        for test, durations in self.test_durations.items():
            if durations and sum(durations) / len(durations) > duration_threshold:
                slow_tests.append(test)
        return slow_tests
    
    def detect_resource_leaks(self, memory_threshold: float = 100.0) -> List[str]:
        """Detect tests that may have resource leaks."""
        leaky_tests = []
        for test, usage in self.resource_usage.items():
            if usage.get('memory', 0) > memory_threshold:
                leaky_tests.append(test)
        return leaky_tests
    
    def record_parallel_conflict(self, test1: str, test2: str, conflict_type: str):
        """Record a parallel execution conflict."""
        self.parallel_conflicts.append({
            'test1': test1,
            'test2': test2,
            'conflict_type': conflict_type,
            'timestamp': time.time()
        })
    
    def get_health_report(self) -> Dict[str, Any]:
        """Generate a comprehensive test health report."""
        return {
            'flaky_tests': self.detect_flaky_tests(),
            'slow_tests': self.detect_slow_tests(),
            'resource_leaks': self.detect_resource_leaks(),
            'parallel_conflicts': len(self.parallel_conflicts),
            'total_tests_monitored': len(self.resource_usage),
            'active_tests': len(TestEnvironmentManager.get_active_tests())
        }


# Global test health monitor
_test_health_monitor = TestHealthMonitor()


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def load_canned_response(prompt_id: str) -> Dict[str, Any]:
    """Load a canned LLM response for the given prompt ID."""

    return get_canned_response(prompt_id)


def create_mock_llm_response(
    content: str,
    raw_data: Optional[Dict[str, Any]] = None,
) -> MagicMock:
    """Create a CompletionResponse-like mock object."""

    response = _factory_create_mock_llm_response(content)
    if raw_data:
        response.raw.update(raw_data)
        usage = response.raw.get("usage")
        if isinstance(usage, dict):
            if "prompt_tokens" in raw_data:
                usage["prompt_tokens"] = raw_data["prompt_tokens"]
            if "completion_tokens" in raw_data:
                usage["completion_tokens"] = raw_data["completion_tokens"]
            total_tokens = raw_data.get("total_tokens")
            if total_tokens is not None:
                usage["total_tokens"] = total_tokens
            else:
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                usage["total_tokens"] = prompt_tokens + completion_tokens
    return response


def create_mock_node(
    node_id: str,
    text: str,
    *,
    score: float = 0.9,
    collection: str = "Aristotle",
    **extra_payload: Any,
) -> MagicMock:
    """Create a Qdrant-like node mock."""

    return _factory_create_mock_node(
        node_id=node_id,
        text=text,
        score=score,
        collection=collection,
        **extra_payload,
    )


def assert_response_schema(
    response_data: Dict[str, Any],
    expected_fields: Iterable[str],
    field_types: Optional[Dict[str, type]] = None,
) -> None:
    """Assert that the response matches the expected schema."""

    _helper_assert_response_schema(response_data, expected_fields, field_types)


def assert_keywords_present(
    text: str,
    keywords: Iterable[str],
    *,
    case_sensitive: bool = False,
    require_all: bool = True,
) -> None:
    """Assert that keywords appear in the text."""


def normalize_test_philosopher_name(philosopher_name: str) -> str:
    """Normalize a philosopher name for use in tests."""
    return philosopher_mapper.normalize_philosopher_name(philosopher_name)


def get_philosopher_for_category(category: str) -> str:
    """Get the appropriate philosopher for a test category."""
    return philosopher_mapper.get_philosopher_for_category(category)


def select_philosopher_for_test(prompt_data: Dict[str, Any], 
                               test_variant: Optional[Dict[str, Any]] = None) -> str:
    """Select the most appropriate philosopher for a test scenario."""
    return select_test_philosopher(prompt_data, test_variant)


def get_test_philosopher_selector():
    """Get the test philosopher selector instance."""
    return test_philosopher_selector

    _helper_assert_keywords_present(
        text,
        keywords,
        case_sensitive=case_sensitive,
        require_all=require_all,
    )


def assert_philosophy_response_valid(response_data: Dict[str, Any]) -> None:
    """Assert that /ask_philosophy responses include required fields."""

    _helper_assert_philosophy_response_valid(response_data)


def assert_hybrid_query_response_valid(
    response_data: Any,
    *,
    raw_mode: bool = False,
    vet_mode: bool = False,
) -> None:
    """Assert structure of /query_hybrid responses for different modes."""

    _helper_assert_hybrid_query_response_valid(
        response_data,
        raw_mode=raw_mode,
        vet_mode=vet_mode,
    )


def assert_ask_response_valid(response_data: Any) -> None:
    """Assert that /ask response payloads are valid."""

    _helper_assert_ask_response_valid(response_data)


def get_prompt_completion_mock(prompt_id: str) -> MagicMock:
    """Create a canned CompletionResponse-like mock for *prompt_id*."""

    canned = load_canned_response(prompt_id)
    payload = canned.get("mock_response", {})
    content = payload.get("content")
    if content is None:
        raise KeyError(f"Canned response for prompt_id={prompt_id} missing 'content'")

    return create_mock_llm_response(content, raw_data=payload.get("raw"))


def create_mock_nodes_dict(
    collection: str,
    *,
    num_nodes: int = 5,
    vector_types: Optional[Iterable[str]] = None,
    base_text: str = "Philosophical passage",
) -> Dict[str, List[MagicMock]]:
    """Create mapping of vector type to mock nodes."""

    return _factory_create_mock_nodes_dict(
        collection,
        num_nodes=num_nodes,
        vector_types=vector_types,
        base_text=base_text,
    )


def create_conversation_history(
    messages: Iterable[tuple[str, str]],
) -> List[Any]:
    """Create conversation history objects for repeated queries."""

    return _factory_create_conversation_history(messages)


# ---------------------------------------------------------------------------
# Session-scoped fixtures for expensive setup operations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def session_resource_manager() -> TestResourceManager:
    """Session-scoped resource manager for expensive setup operations."""
    return _session_resource_manager


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Session-scoped test database URL configuration."""
    return "sqlite:///./test_session.db"


@pytest.fixture(scope="session")
def base_test_environment() -> Dict[str, str]:
    """Session-scoped base environment configuration."""
    return TestEnvironmentManager.get_standard_test_env()


@pytest.fixture(scope="session")
def session_mock_factories() -> Dict[str, callable]:
    """Session-scoped mock factory functions for performance optimization."""
    return {
        'llm_manager': lambda: _create_optimized_llm_manager_mock(),
        'qdrant_manager': lambda: _create_optimized_qdrant_manager_mock(),
        'cache_service': lambda: _create_optimized_cache_service_mock(),
        'auth_service': lambda: _create_optimized_auth_service_mock(),
    }


def _create_optimized_llm_manager_mock() -> MagicMock:
    """Create an optimized LLM manager mock with minimal setup."""
    manager = MagicMock()
    
    # Configuration methods
    manager.set_llm_context_window = MagicMock()
    manager.set_temperature = MagicMock()
    
    # Core async methods
    manager.aquery = AsyncMock(return_value=create_mock_llm_response("Optimized mock response."))
    manager.achat = AsyncMock(return_value=create_mock_llm_response("Optimized mock response."))
    manager.avet = AsyncMock(return_value=create_mock_llm_response("Optimized mock response."))
    manager.vet = AsyncMock(return_value=create_mock_llm_response("Content is appropriate."))
    
    # Streaming methods
    async def mock_stream():
        yield MagicMock(delta="Test")
        yield MagicMock(delta=" stream")
        yield MagicMock(delta=" response")

    manager.aquery_stream = AsyncMock(side_effect=lambda *a, **k: mock_stream())
    manager.achat_stream = AsyncMock(side_effect=lambda *a, **k: mock_stream())
    
    # Vector generation methods
    manager.generate_splade_vector = AsyncMock(return_value={"indices": [1, 2, 3], "values": [0.5, 0.3, 0.2]})
    manager.generate_dense_vector = AsyncMock(return_value=[0.1] * 4096)  # Updated to 4096-dim
    manager.get_embedding = AsyncMock(return_value=[0.1] * 384)
    manager.aembed = AsyncMock(return_value=[0.1] * 384)
    
    # Factory methods for service initialization
    manager.start = AsyncMock(return_value=manager)
    manager.aclose = AsyncMock()
    
    # Properties that might be accessed
    manager.llm = MagicMock()
    manager.embed_model = MagicMock()
    manager.splade_model = MagicMock()
    manager.splade_tokenizer = MagicMock()
    
    # Cleanup methods
    manager.close = AsyncMock()
    manager.cleanup = AsyncMock()
    manager.shutdown = MagicMock()
    
    return manager


def _create_optimized_qdrant_manager_mock() -> MagicMock:
    """Create an optimized Qdrant manager mock with minimal setup."""
    manager = MagicMock()
    manager.query_hybrid = AsyncMock(return_value={})
    manager.gather_points_and_sort = AsyncMock(return_value=[])
    manager.get_collections = AsyncMock(return_value=[])
    manager.validate_connection = AsyncMock(return_value=True)
    manager.close = AsyncMock()
    manager.cleanup = AsyncMock()
    return manager


def _create_optimized_cache_service_mock() -> AsyncMock:
    """Create an optimized cache service mock with minimal setup."""
    mock_cache_service = AsyncMock()
    mock_cache_service.get.return_value = None
    mock_cache_service.set.return_value = True
    mock_cache_service.delete.return_value = True
    mock_cache_service.close = AsyncMock()
    return mock_cache_service


def _create_optimized_auth_service_mock() -> MagicMock:
    """Create an optimized auth service mock with minimal setup."""
    mock_auth_service = MagicMock()
    mock_auth_service.get_available_providers.return_value = {"github": {"name": "GitHub"}}
    mock_auth_service.create_anonymous_session = AsyncMock(return_value="test-session-123")
    mock_auth_service.get_user_context = AsyncMock(return_value={"session_id": None})
    mock_auth_service.delete_session = AsyncMock(return_value=False)
    return mock_auth_service


@pytest.fixture
def isolated_test_db_url(request) -> str:
    """Generate isolated database URL for individual tests."""
    test_name = request.node.name if hasattr(request, 'node') else "default"
    return TestEnvironmentManager.get_test_database_url(test_name)


@pytest.fixture
def test_state_cleanup(test_resource_manager: TestResourceManager):
    """Fixture to ensure proper test state cleanup."""
    setup_test_state_cleanup(test_resource_manager)
    yield
    # Cleanup happens automatically via resource manager


@pytest.fixture(scope="session", autouse=True)
def session_cleanup(session_resource_manager: TestResourceManager):
    """Session-scoped cleanup fixture that runs automatically."""
    yield
    # Use asyncio.run for session cleanup since we can't use async fixtures at session scope
    import asyncio
    try:
        asyncio.run(session_resource_manager.cleanup_all())
    except RuntimeError:
        # If there's already an event loop running, create a new one
        import threading
        def cleanup_in_thread():
            asyncio.run(session_resource_manager.cleanup_all())
        thread = threading.Thread(target=cleanup_in_thread)
        thread.start()
        thread.join()


# ---------------------------------------------------------------------------
# Function-scoped fixtures for test isolation
# ---------------------------------------------------------------------------


@pytest.fixture
def test_resource_manager() -> TestResourceManager:
    """Function-scoped resource manager for individual test cleanup."""
    manager = TestResourceManager()
    yield manager
    # Cleanup happens automatically via async context


@pytest.fixture
def service_mock_manager() -> ServiceMockManager:
    """Function-scoped comprehensive mock manager."""
    manager = ServiceMockManager()
    yield manager
    # Cleanup happens automatically via async context


@pytest.fixture
def database_mock_manager() -> DatabaseMockManager:
    """Function-scoped database mock manager."""
    manager = DatabaseMockManager()
    yield manager
    # Cleanup happens automatically via async context


@pytest.fixture
def auth_mock_helper() -> AuthMockHelper:
    """Function-scoped authentication mock helper."""
    helper = AuthMockHelper()
    yield helper
    helper.cleanup_all()


@pytest.fixture
async def async_test_cleanup(test_resource_manager: TestResourceManager):
    """Async cleanup fixture for function-scoped tests."""
    yield test_resource_manager
    await test_resource_manager.cleanup_all()


# ---------------------------------------------------------------------------
# Database Session Mock Fixtures (Task 3.2)
# ---------------------------------------------------------------------------


@pytest.fixture
async def mock_db_session(
    test_resource_manager: TestResourceManager,
    database_mock_manager: DatabaseMockManager
):
    """Function-scoped database session mock using DatabaseMockManager.

    Provides a properly configured AsyncSession mock using the DatabaseMockManager
    infrastructure for consistent behavior across tests.

    Example usage:
        async def test_database_operation(mock_db_session):
            # Configure query result
            mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_user

            # Use in code under test
            result = await session.execute(select(User).where(User.id == 1))
            user = result.scalar_one_or_none()
    """
    # Use DatabaseMockManager to create and configure session
    session_id = "test_session"
    session_mock = database_mock_manager.create_async_session_mock(session_id)

    # Configure default empty result mock
    result_mock = database_mock_manager.create_result_mock(rows=[], rowcount=0)
    session_mock.execute.return_value = result_mock

    # Register session for cleanup
    test_resource_manager.register_mock("mock_db_session", session_mock)
    test_resource_manager.register_async_resource(session_mock)

    yield session_mock

    # Cleanup happens via test_resource_manager


@pytest.fixture
def mock_db_session_factory(database_mock_manager: DatabaseMockManager):
    """Factory for creating multiple unique database session mocks.

    Creates a new unique session mock for each call, useful for tests that need
    multiple independent sessions or session lifecycle testing.

    Example usage:
        def test_multiple_sessions(mock_db_session_factory):
            async with mock_db_session_factory() as session1:
                # Use first session
                pass
            async with mock_db_session_factory() as session2:
                # Use second, independent session
                pass
    """
    session_counter = [0]  # Mutable counter for unique IDs

    @asynccontextmanager
    async def _session_factory():
        session_counter[0] += 1
        session_id = f"factory_session_{session_counter[0]}"

        # Create unique session using DatabaseMockManager
        session_mock = database_mock_manager.create_async_session_mock(session_id)

        # Configure default empty result mock
        result_mock = database_mock_manager.create_result_mock(rows=[], rowcount=0)
        session_mock.execute.return_value = result_mock

        try:
            yield session_mock
        finally:
            # Cleanup session
            await session_mock.close()

    return _session_factory


@pytest.fixture
def configure_db_query_results(mock_db_session):
    """Helper fixture to easily configure database query results.

    Example usage:
        def test_user_query(mock_db_session, configure_db_query_results):
            mock_user = MagicMock(id=1, username="testuser")
            configure_db_query_results(mock_db_session, "scalar_one_or_none", mock_user)

            # Query will return mock_user
            result = await session.execute(select(User))
            user = result.scalar_one_or_none()
            assert user == mock_user
    """
    def _configure(session_mock, method_name: str, return_value: Any):
        """Configure a specific query method to return a value."""
        if hasattr(session_mock, method_name):
            getattr(session_mock, method_name).return_value = return_value
        elif hasattr(session_mock.execute.return_value, method_name):
            getattr(session_mock.execute.return_value, method_name).return_value = return_value
        else:
            # Try to set on execute result mock
            result_mock = session_mock.execute.return_value
            setattr(result_mock, method_name, AsyncMock(return_value=return_value))

    return _configure


@pytest.fixture(autouse=True)
def performance_monitor(request):
    """Monitor test performance and resource usage with health tracking (autouse for all tests)."""
    import time
    import psutil
    import os
    
    test_name = request.node.name
    
    # Record start metrics
    start_time = time.time()
    process = psutil.Process(os.getpid())
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    # Check for parallel execution conflicts
    active_tests = TestEnvironmentManager.get_active_tests()
    if len(active_tests) > 1:
        for other_test in active_tests:
            if other_test != test_name:
                _test_health_monitor.record_parallel_conflict(
                    test_name, other_test, "concurrent_execution"
                )
    
    yield
    
    # Record end metrics
    end_time = time.time()
    end_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    duration = end_time - start_time
    memory_delta = end_memory - start_memory
    
    # Determine if test passed (simplified check)
    test_passed = not hasattr(request.node, 'rep_call') or request.node.rep_call.passed
    
    # Record test results in health monitor
    _test_health_monitor.record_test_result(test_name, test_passed, duration, memory_delta)
    
    # Log performance metrics for slow tests
    if duration > 1.0:  # Tests taking more than 1 second
        print(f"\n[PERF] {test_name}: {duration:.2f}s, memory: {memory_delta:+.1f}MB")
    
    # Warn about memory leaks
    if memory_delta > 50:  # More than 50MB increase
        print(f"\n[MEMORY] {test_name}: Potential memory leak (+{memory_delta:.1f}MB)")
    
    # Warn about flaky tests
    if test_name in _test_health_monitor.detect_flaky_tests(failure_threshold=2):
        print(f"\n[FLAKY] {test_name}: This test has failed multiple times - may be flaky")


@pytest.fixture
async def mock_environment(request, test_resource_manager: TestResourceManager, base_test_environment: Dict[str, str]) -> None:
    """Apply standardized environment variables for testing with proper cleanup and isolation."""

    test_name = request.node.name if hasattr(request, 'node') else "default"
    
    # Ensure test isolation with parallel safety
    await TestEnvironmentManager.ensure_test_isolation(test_name)

    # Create isolated test environment
    test_env = base_test_environment.copy()
    
    # Create unique test database for this test with thread/process isolation
    test_env["ONTOLOGIC_DB_URL"] = TestEnvironmentManager.get_test_database_url(test_name)
    
    # Add test-specific isolation markers
    test_env["TEST_NAME"] = test_name
    test_env["TEST_ISOLATION_ID"] = f"{os.getpid()}_{threading.get_ident()}_{hash(test_name) % 10000}"
    
    # Setup comprehensive cleanup with test name
    setup_test_state_cleanup(test_resource_manager, test_name)
    
    with patch.dict(os.environ, test_env, clear=False):
        yield
        # Cleanup happens via test_resource_manager and TestEnvironmentManager


@pytest.fixture(autouse=True)
async def test_isolation_guard(request):
    """Ensure proper test isolation and state cleanup between tests (autouse)."""
    test_name = request.node.name
    
    # Pre-test isolation setup
    await TestEnvironmentManager.ensure_test_isolation(test_name)
    
    yield
    
    # Post-test cleanup
    await TestEnvironmentManager.cleanup_test_state(test_name)


@pytest.fixture
def mock_llm_manager(test_resource_manager: TestResourceManager, session_mock_factories: Dict[str, callable]) -> MagicMock:
    """Provide a mocked LLMManager with async methods and resource tracking (optimized)."""
    
    # Try to get from cache or pool first
    cached_manager = test_resource_manager.get_cached_resource("llm_manager")
    if cached_manager:
        cached_manager.reset_mock()
        test_resource_manager.register_mock("llm_manager", cached_manager)
        test_resource_manager.register_async_resource(cached_manager)
        return cached_manager
    
    # Create new manager using optimized factory
    manager = test_resource_manager.get_or_create_mock("llm_manager", session_mock_factories["llm_manager"])

    # Register for cleanup
    test_resource_manager.register_mock("llm_manager", manager)
    test_resource_manager.register_async_resource(manager)
    test_resource_manager.cache_resource("llm_manager", manager)

    return manager


@pytest.fixture
def mock_qdrant_manager(test_resource_manager: TestResourceManager, session_mock_factories: Dict[str, callable]) -> MagicMock:
    """Provide a mocked QdrantManager with async methods and resource tracking (optimized)."""
    
    # Try to get from cache or pool first
    cached_manager = test_resource_manager.get_cached_resource("qdrant_manager")
    if cached_manager:
        cached_manager.reset_mock()
        test_resource_manager.register_mock("qdrant_manager", cached_manager)
        test_resource_manager.register_async_resource(cached_manager)
        return cached_manager
    
    # Create new manager using optimized factory
    manager = test_resource_manager.get_or_create_mock("qdrant_manager", session_mock_factories["qdrant_manager"])

    # Register for cleanup
    test_resource_manager.register_mock("qdrant_manager", manager)
    test_resource_manager.register_async_resource(manager)
    test_resource_manager.cache_resource("qdrant_manager", manager)

    return manager


@pytest.fixture
def comprehensive_service_mocks(
    service_mock_manager: ServiceMockManager,
    test_resource_manager: TestResourceManager,
    session_mock_factories: Dict[str, callable]
) -> Dict[str, Any]:
    """Comprehensive service mocks using the enhanced mocking framework (optimized)."""
    
    # Check if we have cached comprehensive mocks
    cached_mocks = test_resource_manager.get_cached_resource("comprehensive_service_mocks")
    if cached_mocks:
        # Reset all mocks in the cached set
        for mock_name, mock_obj in cached_mocks.items():
            if hasattr(mock_obj, 'reset_mock'):
                mock_obj.reset_mock()
        return cached_mocks
    
    # Create new comprehensive mocks
    mocks = service_mock_manager.create_all_service_mocks(
        payments_enabled=False,  # Default to disabled for most tests
        cache_enabled=True
    )
    
    # Cache for reuse
    test_resource_manager.cache_resource("comprehensive_service_mocks", mocks)
    
    return mocks


@pytest.fixture
def mock_all_services(
    mock_llm_manager: MagicMock, 
    mock_qdrant_manager: MagicMock,
    test_resource_manager: TestResourceManager
) -> Dict[str, MagicMock]:
    """Patch dependency injection to use mocked services with resource tracking."""

    # Create additional service mocks
    mock_cache_service = MagicMock()
    mock_cache_service.get = AsyncMock(return_value=None)
    mock_cache_service.set = AsyncMock(return_value=True)
    mock_cache_service.delete = AsyncMock(return_value=True)
    mock_cache_service.close = AsyncMock()
    
    # Register additional mocks
    test_resource_manager.register_mock("cache_service", mock_cache_service)
    test_resource_manager.register_async_resource(mock_cache_service)

    # Also create a bypass for the cache decorators that might interfere
    def passthrough_decorator(*args, **kwargs):
        """Decorator that just passes through the function unchanged."""
        def decorator(func):
            return func
        if args and callable(args[0]):
            return args[0]
        return decorator

    patches = [
        # Patch the underlying dependencies that LLMManager/QdrantManager use
        patch("app.services.llm_manager.Ollama"),
        patch("app.services.llm_manager.OllamaEmbedding"),
        patch("app.services.llm_manager.AutoTokenizer"),
        patch("app.services.llm_manager.AutoModelForMaskedLM"),
        patch("app.services.qdrant_manager.AsyncQdrantClient"),
        # Patch the underlying class constructors to return our mocks
        patch("app.services.llm_manager.LLMManager", return_value=mock_llm_manager),
        patch("app.services.qdrant_manager.QdrantManager", return_value=mock_qdrant_manager),
        patch("app.services.cache_service.RedisCacheService", return_value=mock_cache_service),
        patch("app.core.database.init_db", new=MagicMock()),
    ]
    
    # Start all patches
    started_patches = [p.__enter__() for p in patches]
    
    # Register cleanup callback to stop patches
    def cleanup_patches():
        for p in reversed(patches):
            try:
                p.__exit__(None, None, None)
            except Exception:
                pass
    
    test_resource_manager.add_cleanup_callback(cleanup_patches)
    
    return {
        "llm": mock_llm_manager, 
        "qdrant": mock_qdrant_manager,
        "cache": mock_cache_service
    }


@pytest.fixture
async def async_client(mock_environment: None, mock_all_services: Dict[str, MagicMock]):
    """Create an AsyncClient instance with lifespan management for modern testing."""
    from app.main import app
    import app.core.dependencies as deps
    from unittest.mock import AsyncMock

    # Create async-aware cache service mock
    mock_cache_service = AsyncMock()
    mock_cache_service.get.return_value = None  # Default: cache miss
    mock_cache_service.set.return_value = True  # Default: cache set succeeds

    # Create async-aware chat service mocks
    mock_chat_history_service = AsyncMock()
    mock_chat_history_service.get_conversation_history.return_value = []
    mock_chat_history_service.store_message.return_value = None

    mock_chat_qdrant_service = AsyncMock()
    mock_chat_qdrant_service.store_message_embedding.return_value = None

    # Create async-aware workflow service mocks
    mock_expansion_service = AsyncMock()
    mock_expansion_service.expand_query.return_value = ["expanded query"]
    
    mock_paper_workflow = AsyncMock()
    mock_paper_workflow.create_draft.return_value = "test-draft-id"
    mock_paper_workflow.generate_sections.return_value = {"sections": ["test section"]}
    
    mock_review_workflow = AsyncMock()
    mock_review_workflow.review_draft.return_value = {"review": "test review"}

    # Create async-aware prompt renderer mock
    mock_prompt_renderer = AsyncMock()
    mock_prompt_renderer.render.return_value = "test prompt"

    # Create async-aware payment service mocks
    mock_payment_service = AsyncMock()
    mock_payment_service.create_checkout_session.return_value = {"url": "test-url"}
    
    mock_subscription_manager = AsyncMock()
    mock_subscription_manager.get_user_subscription.return_value = None
    
    mock_billing_service = AsyncMock()
    mock_billing_service.get_usage_summary.return_value = {"usage": 0}

    # Create async-aware auth service mock
    mock_auth_service = AsyncMock()
    mock_auth_service.verify_token.return_value = {"user_id": "test-user"}

    # CRITICAL FIX: Initialize services in app.state to prevent RuntimeError
    # This ensures that dependency injection functions can access services from app.state
    app.state.startup_errors = []
    app.state.serving_enabled = True
    app.state.services_ready = {
        "database": True,
        "llm_manager": True,
        "qdrant_manager": True,
        "cache_service": True,
        "prompt_renderer": True,
        "expansion_service": True,
        "chat_history_service": True,
        "chat_qdrant_service": True,
        "paper_workflow": True,
        "review_workflow": True,
        "payment_service": True,
        "subscription_manager": True,
        "billing_service": True,
        "refund_dispute_service": True,
    }
    
    # Store mocked services in app.state (this is what dependency functions check)
    app.state.llm_manager = mock_all_services["llm"]
    app.state.qdrant_manager = mock_all_services["qdrant"]
    app.state.cache_service = mock_cache_service
    app.state.chat_history_service = mock_chat_history_service
    app.state.chat_qdrant_service = mock_chat_qdrant_service
    app.state.expansion_service = mock_expansion_service
    app.state.paper_workflow = mock_paper_workflow
    app.state.review_workflow = mock_review_workflow
    app.state.prompt_renderer = mock_prompt_renderer
    app.state.payment_service = mock_payment_service
    app.state.subscription_manager = mock_subscription_manager
    app.state.billing_service = mock_billing_service
    app.state.auth_service = mock_auth_service

    # Configure dependency overrides as backup (some tests might still use these)
    app.dependency_overrides[deps.get_llm_manager] = lambda: mock_all_services["llm"]
    app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_all_services["qdrant"]
    app.dependency_overrides[deps.get_cache_service] = lambda: mock_cache_service
    app.dependency_overrides[deps.get_chat_history_service] = lambda: mock_chat_history_service
    app.dependency_overrides[deps.get_chat_qdrant_service] = lambda: mock_chat_qdrant_service
    app.dependency_overrides[deps.get_expansion_service] = lambda: mock_expansion_service
    app.dependency_overrides[deps.get_paper_workflow] = lambda: mock_paper_workflow
    app.dependency_overrides[deps.get_review_workflow] = lambda: mock_review_workflow
    app.dependency_overrides[deps.get_prompt_renderer] = lambda: mock_prompt_renderer
    app.dependency_overrides[deps.get_payment_service] = lambda: mock_payment_service
    app.dependency_overrides[deps.get_subscription_manager] = lambda: mock_subscription_manager
    app.dependency_overrides[deps.get_billing_service] = lambda: mock_billing_service
    app.dependency_overrides[deps.get_auth_service] = lambda: mock_auth_service

    try:
        # Create async client with ASGI transport
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        # Clean up dependency overrides and app state after test
        app.dependency_overrides.clear()
        # Clear app.state to prevent interference between tests
        if hasattr(app.state, 'llm_manager'):
            delattr(app.state, 'llm_manager')
        if hasattr(app.state, 'qdrant_manager'):
            delattr(app.state, 'qdrant_manager')
        if hasattr(app.state, 'cache_service'):
            delattr(app.state, 'cache_service')
        if hasattr(app.state, 'chat_history_service'):
            delattr(app.state, 'chat_history_service')
        if hasattr(app.state, 'chat_qdrant_service'):
            delattr(app.state, 'chat_qdrant_service')
        if hasattr(app.state, 'expansion_service'):
            delattr(app.state, 'expansion_service')
        if hasattr(app.state, 'paper_workflow'):
            delattr(app.state, 'paper_workflow')
        if hasattr(app.state, 'review_workflow'):
            delattr(app.state, 'review_workflow')
        if hasattr(app.state, 'prompt_renderer'):
            delattr(app.state, 'prompt_renderer')
        if hasattr(app.state, 'payment_service'):
            delattr(app.state, 'payment_service')
        if hasattr(app.state, 'subscription_manager'):
            delattr(app.state, 'subscription_manager')
        if hasattr(app.state, 'billing_service'):
            delattr(app.state, 'billing_service')
        if hasattr(app.state, 'auth_service'):
            delattr(app.state, 'auth_service')

@pytest.fixture
def test_app_with_mocked_services(mock_environment: None, mock_all_services: Dict[str, MagicMock]):
    """Create a FastAPI app with mocked services in app.state for integration tests."""
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from unittest.mock import AsyncMock

    # Create a test lifespan that initializes mocked services in app.state
    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        """Test lifespan that initializes mocked services in app.state."""
        # Initialize app state with mocked services
        app.state.startup_errors = []
        app.state.serving_enabled = True
        app.state.services_ready = {
            "database": True,
            "llm_manager": True,
            "qdrant_manager": True,
            "cache_service": True,
            "prompt_renderer": True,
            "expansion_service": True,
            "chat_history_service": True,
            "chat_qdrant_service": True,
            "paper_workflow": True,
            "review_workflow": True,
            "payment_service": True,
            "subscription_manager": True,
            "billing_service": True,
            "refund_dispute_service": True,
        }
        
        # Set up all mocked services in app.state
        app.state.llm_manager = mock_all_services["llm"]
        app.state.qdrant_manager = mock_all_services["qdrant"]
        app.state.cache_service = mock_all_services["cache"]
        
        # Create additional service mocks
        mock_prompt_renderer = AsyncMock()
        mock_prompt_renderer.render.return_value = "test prompt"
        app.state.prompt_renderer = mock_prompt_renderer
        
        mock_expansion_service = AsyncMock()
        mock_expansion_service.expand_query.return_value = ["expanded query"]
        app.state.expansion_service = mock_expansion_service
        
        mock_chat_history_service = AsyncMock()
        mock_chat_history_service.get_conversation_history.return_value = []
        app.state.chat_history_service = mock_chat_history_service
        
        mock_chat_qdrant_service = AsyncMock()
        mock_chat_qdrant_service.store_message_embedding.return_value = None
        app.state.chat_qdrant_service = mock_chat_qdrant_service
        
        mock_paper_workflow = AsyncMock()
        mock_paper_workflow.create_draft.return_value = "test-draft-id"
        app.state.paper_workflow = mock_paper_workflow
        
        mock_review_workflow = AsyncMock()
        mock_review_workflow.review_draft.return_value = {"review": "test review"}
        app.state.review_workflow = mock_review_workflow
        
        mock_auth_service = AsyncMock()
        mock_auth_service.verify_token.return_value = {"user_id": "test-user"}
        app.state.auth_service = mock_auth_service
        
        # Payment services (can be None for graceful degradation)
        app.state.payment_service = None
        app.state.subscription_manager = None
        app.state.billing_service = None
        app.state.refund_dispute_service = None
        
        yield
        # No cleanup needed for mocks

    # Create a fresh FastAPI app with test lifespan
    app = FastAPI(title="Ontologic API Test", lifespan=test_lifespan)

    # Configure app with routers and middleware
    from app.router import router
    from app.core.rate_limiting import limiter
    from slowapi.middleware import SlowAPIMiddleware

    previous_limiter_enabled = limiter.enabled
    app.state.limiter = limiter
    limiter.enabled = False
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(router)
    
    try:
        yield app
    finally:
        limiter.enabled = previous_limiter_enabled

@pytest.fixture  
def test_client(mock_all_services: Dict[str, MagicMock]) -> TestClient:
    """Legacy TestClient fixture - prefer async_client for new tests."""
    from app.main import app
    from app.core import dependencies as deps
    from unittest.mock import AsyncMock
    
    # CRITICAL FIX: Initialize services in app.state to prevent RuntimeError
    app.state.startup_errors = []
    app.state.serving_enabled = True
    app.state.services_ready = {
        "database": True,
        "llm_manager": True,
        "qdrant_manager": True,
        "cache_service": True,
        "prompt_renderer": True,
        "expansion_service": True,
        "chat_history_service": True,
        "chat_qdrant_service": True,
        "paper_workflow": True,
        "review_workflow": True,
        "payment_service": True,
        "subscription_manager": True,
        "billing_service": True,
        "refund_dispute_service": True,
    }
    
    # Store mocked services in app.state (this is what dependency functions check)
    app.state.llm_manager = mock_all_services["llm"]
    app.state.qdrant_manager = mock_all_services["qdrant"]
    app.state.cache_service = mock_all_services["cache"]
    
    # Create additional service mocks for app.state
    mock_prompt_renderer = AsyncMock()
    mock_prompt_renderer.render.return_value = "test prompt"
    app.state.prompt_renderer = mock_prompt_renderer
    
    mock_expansion_service = AsyncMock()
    mock_expansion_service.expand_query.return_value = ["expanded query"]
    app.state.expansion_service = mock_expansion_service
    
    mock_chat_history_service = AsyncMock()
    mock_chat_history_service.get_conversation_history.return_value = []
    app.state.chat_history_service = mock_chat_history_service
    
    mock_chat_qdrant_service = AsyncMock()
    mock_chat_qdrant_service.store_message_embedding.return_value = None
    app.state.chat_qdrant_service = mock_chat_qdrant_service
    
    mock_paper_workflow = AsyncMock()
    mock_paper_workflow.create_draft.return_value = "test-draft-id"
    app.state.paper_workflow = mock_paper_workflow
    
    mock_review_workflow = AsyncMock()
    mock_review_workflow.review_draft.return_value = {"review": "test review"}
    app.state.review_workflow = mock_review_workflow
    
    from unittest.mock import MagicMock
    mock_auth_service = MagicMock()
    mock_auth_service.verify_token = AsyncMock(return_value={"user_id": "test-user"})
    mock_auth_service.get_available_providers.return_value = {}
    mock_auth_service.create_anonymous_session = AsyncMock(return_value="test-session-123")
    # Default to "not found" behavior to match test expectations
    mock_auth_service.get_user_context = AsyncMock(return_value={"session_id": None})
    mock_auth_service.delete_session = AsyncMock(return_value=False)
    app.state.auth_service = mock_auth_service
    
    # Payment services (can be None for graceful degradation)
    app.state.payment_service = None
    app.state.subscription_manager = None
    app.state.billing_service = None
    app.state.refund_dispute_service = None
    
    # Override dependencies with mocks as backup
    app.dependency_overrides[deps.get_llm_manager] = lambda: mock_all_services["llm"]
    app.dependency_overrides[deps.get_qdrant_manager] = lambda: mock_all_services["qdrant"]
    app.dependency_overrides[deps.get_cache_service] = lambda: mock_all_services["cache"]
    app.dependency_overrides[deps.get_chat_history_service] = lambda: mock_chat_history_service
    app.dependency_overrides[deps.get_chat_qdrant_service] = lambda: mock_chat_qdrant_service
    # Note: auth_service dependency override is handled by individual tests as needed
    
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        # Clean up dependency overrides and app state
        app.dependency_overrides.clear()
        # Clear app.state to prevent interference between tests
        if hasattr(app.state, 'llm_manager'):
            delattr(app.state, 'llm_manager')
        if hasattr(app.state, 'qdrant_manager'):
            delattr(app.state, 'qdrant_manager')
        if hasattr(app.state, 'cache_service'):
            delattr(app.state, 'cache_service')
        if hasattr(app.state, 'prompt_renderer'):
            delattr(app.state, 'prompt_renderer')
        if hasattr(app.state, 'expansion_service'):
            delattr(app.state, 'expansion_service')
        if hasattr(app.state, 'chat_history_service'):
            delattr(app.state, 'chat_history_service')
        if hasattr(app.state, 'chat_qdrant_service'):
            delattr(app.state, 'chat_qdrant_service')
        if hasattr(app.state, 'paper_workflow'):
            delattr(app.state, 'paper_workflow')
        if hasattr(app.state, 'review_workflow'):
            delattr(app.state, 'review_workflow')
        if hasattr(app.state, 'auth_service'):
            delattr(app.state, 'auth_service')
        client.close()


# ---------------------------------------------------------------------------
# LLMManager Test Isolation Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_manager_for_integration_tests():
    """Create a comprehensive LLMManager mock specifically for integration tests."""
    from unittest.mock import AsyncMock, MagicMock
    
    mock = MagicMock()
    
    # Core async methods with realistic return values
    mock.aquery = AsyncMock()
    mock.aquery.return_value = MagicMock(text="Integration test LLM response")
    
    mock.achat = AsyncMock()
    mock.achat.return_value = MagicMock(message=MagicMock(content="Integration test chat response"))
    
    mock.vet = AsyncMock()
    mock.vet.return_value = MagicMock(text="Content is appropriate for integration test")
    
    # Streaming methods
    async def mock_stream():
        yield MagicMock(delta="Integration")
        yield MagicMock(delta=" test")
        yield MagicMock(delta=" stream")

    mock.aquery_stream = AsyncMock(side_effect=lambda *a, **k: mock_stream())
    mock.achat_stream = AsyncMock(side_effect=lambda *a, **k: mock_stream())
    
    # Vector generation methods
    mock.generate_dense_vector = AsyncMock(return_value=[0.1] * 4096)
    mock.generate_splade_vector = AsyncMock(return_value={"token1": 0.5, "token2": 0.3})
    mock.aembed = AsyncMock(return_value=[0.1] * 384)
    
    # Configuration methods
    mock.set_temperature = MagicMock()
    mock.set_llm_context_window = MagicMock()
    
    # Factory methods
    mock.start = AsyncMock(return_value=mock)
    mock.aclose = AsyncMock()
    mock.shutdown = MagicMock()
    
    # Properties
    mock.llm = MagicMock()
    mock.embed_model = MagicMock()
    mock.splade_model = MagicMock()
    mock.splade_tokenizer = MagicMock()
    
    return mock

@pytest.fixture
def mock_service_initialization_failure():
    """Mock service initialization failures for testing error handling."""
    from unittest.mock import patch, AsyncMock
    
    # Mock LLMManager.start to raise initialization error
    with patch('app.services.llm_manager.LLMManager.start') as mock_start:
        mock_start.side_effect = ConnectionError("LLM service unavailable in test")
        yield mock_start

@pytest.fixture
def mock_workflow_services():
    """Create comprehensive workflow service mocks for integration tests."""
    from unittest.mock import AsyncMock, MagicMock
    
    # Paper workflow mock
    paper_workflow = AsyncMock()
    paper_workflow.create_draft = AsyncMock(return_value="test-draft-123")
    paper_workflow.generate_sections = AsyncMock(return_value={
        "sections": ["Introduction", "Analysis", "Conclusion"],
        "draft_id": "test-draft-123"
    })
    
    # Review workflow mock
    review_workflow = AsyncMock()
    review_workflow.review_draft = AsyncMock(return_value={
        "review": "Test review content",
        "suggestions": ["Suggestion 1", "Suggestion 2"]
    })
    
    # Expansion service mock
    expansion_service = AsyncMock()
    expansion_service.expand_query = AsyncMock(return_value=[
        "expanded query 1",
        "expanded query 2"
    ])
    
    return {
        "paper_workflow": paper_workflow,
        "review_workflow": review_workflow,
        "expansion_service": expansion_service
    }

# ---------------------------------------------------------------------------
# Additional helper assertions specific to philosophy responses
# ---------------------------------------------------------------------------


def assert_philosophy_response_structure(response_data: Dict[str, Any]) -> None:
    """Combined schema and keyword validation for /ask_philosophy payloads."""

    assert_philosophy_response_valid(response_data)
    assert_response_schema(
        response_data["raw"],
        ["usage"],
        {"usage": dict},
    )


def assert_keywords_for_prompt(prompt_id: str, response_text: str) -> None:
    """Validate that prompt-specific keywords appear in the response."""

    canned = load_canned_response(prompt_id)
    expected_keywords = canned.get("expected_output", {}).get("keywords", [])
    if expected_keywords:
        assert_keywords_present(response_text, expected_keywords, case_sensitive=False, require_all=False)


# ---------------------------------------------------------------------------
# Pytest configuration hooks
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and configure asyncio mode."""

    markers = {
        "llm_test": "Tests that involve LLM interactions",
        "qdrant_test": "Tests that involve Qdrant vector database",
        "integration": "Integration tests requiring multiple services",
    }
    for name, description in markers.items():
        config.addinivalue_line("markers", f"{name}: {description}")

    config.addinivalue_line("markers", "asyncio: mark test as requiring asyncio event loop")
    config.option.asyncio_mode = "auto"


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """Auto-mark collected tests based on filename heuristics and coroutine usage."""

    filename_markers = {
        "ask": pytest.mark.llm_test,
        "philosophy": pytest.mark.llm_test,
        "hybrid": pytest.mark.qdrant_test,
        "refeed": pytest.mark.integration,
    }

    for item in items:
        nodeid_lower = item.nodeid.lower()
        for pattern, marker in filename_markers.items():
            if pattern in nodeid_lower:
                item.add_marker(marker)
        if inspect.iscoroutinefunction(getattr(item, "obj", None)):
            item.add_marker(pytest.mark.asyncio)


def pytest_sessionfinish(session, exitstatus):
    """Generate test health report at the end of the test session."""
    health_report = _test_health_monitor.get_health_report()
    
    print("\n" + "="*60)
    print("TEST HEALTH REPORT")
    print("="*60)
    
    if health_report['flaky_tests']:
        print(f"⚠️  FLAKY TESTS ({len(health_report['flaky_tests'])}):")
        for test in health_report['flaky_tests']:
            print(f"   - {test}")
    
    if health_report['slow_tests']:
        print(f"🐌 SLOW TESTS ({len(health_report['slow_tests'])}):")
        for test in health_report['slow_tests']:
            print(f"   - {test}")
    
    if health_report['resource_leaks']:
        print(f"💧 POTENTIAL MEMORY LEAKS ({len(health_report['resource_leaks'])}):")
        for test in health_report['resource_leaks']:
            print(f"   - {test}")
    
    if health_report['parallel_conflicts'] > 0:
        print(f"⚡ PARALLEL EXECUTION CONFLICTS: {health_report['parallel_conflicts']}")
    
    print(f"📊 TOTAL TESTS MONITORED: {health_report['total_tests_monitored']}")
    print(f"🔄 ACTIVE TESTS AT END: {health_report['active_tests']}")
    
    if not any([health_report['flaky_tests'], health_report['slow_tests'], 
                health_report['resource_leaks'], health_report['parallel_conflicts']]):
        print("✅ ALL TESTS HEALTHY - No issues detected!")
    
    print("="*60)


# ---------------------------------------------------------------------------
# Utility to assert canned response metadata alignment
# ---------------------------------------------------------------------------


def assert_philosophy_response_valid_with_prompt(
    prompt_id: str,
    response_data: Dict[str, Any],
) -> None:
    """Validate a philosophy response using prompt-specific expectations."""

    assert_philosophy_response_valid(response_data)
    canned = load_canned_response(prompt_id)
    expected = canned.get("expected_output", {})
    keywords = expected.get("keywords", [])
    if keywords:
        assert_keywords_present(response_data["text"], keywords, require_all=False)

    min_length = expected.get("min_length")
    if min_length and len(response_data["text"].strip()) < min_length:
        raise AssertionError(
            f"Response shorter than expected minimum {min_length}; actual length={len(response_data['text'].strip())}"
        )


__all__ = [
    "mock_environment",
    "mock_llm_manager",
    "mock_qdrant_manager",
    "mock_all_services",
    "comprehensive_service_mocks",
    "service_mock_manager",
    "database_mock_manager",
    "auth_mock_helper",
    "async_client",
    "test_client",
    "load_canned_response",
    "create_mock_llm_response",
    "create_mock_node",
    "create_mock_nodes_dict",
    "create_conversation_history",
    "assert_response_schema",
    "assert_keywords_present",
    "assert_philosophy_response_valid",
    "assert_hybrid_query_response_valid",
    "assert_ask_response_valid",
    "assert_philosophy_response_structure",
    "assert_keywords_for_prompt",
    "assert_philosophy_response_valid_with_prompt",
    "get_prompt_completion_mock",
    "override_workflow_deps",
    "sophia_validator",
    "validate_sophia_compliance",
    "payment_settings",
    "mock_payment_service",
    "mock_subscription_manager",
    "mock_billing_service",
    "mock_cache_service",
    "mock_stripe_customer",
    "mock_stripe_subscription",
    "mock_stripe_checkout_session",
    "mock_stripe_api",
    "stripe_webhook_validator",
    "stripe_error_simulator",
    # Database session mock fixtures (Task 3.2)
    "mock_db_session",
    "mock_db_session_factory",
    "configure_db_query_results",
    # Authentication mock fixtures (Task 3.3)
    "mock_auth_token",
    "mock_user_free_tier",
    "mock_user_premium_tier",
    "mock_user_admin",
    "mock_auth_service_with_user",
    "make_authenticated_request",
    "override_auth_dependency",
]


# ---------------------------------------------------------------------------
# Shared fixtures for dependency overrides in router tests
# ---------------------------------------------------------------------------


@pytest.fixture
def override_workflow_deps(test_client: TestClient):
    """Provide helper to temporarily override workflow dependencies."""

    overrides: Dict[Any, Any] = {}

    def register(providers: Dict[Any, Any]) -> None:
        overrides.update(providers)
        for dependency, provider in providers.items():
            test_client.app.dependency_overrides[dependency] = provider

    yield register

    for dependency in overrides:
        test_client.app.dependency_overrides.pop(dependency, None)


# ---------------------------------------------------------------------------
# Sophia validation fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sophia_validator():
    """Provide Sophia validator for validating responses against Expected Output specifications.

    Usage in tests:
        def test_response_meets_sophia_specs(sophia_validator):
            result = sophia_validator.validate_response("prompt_001_trolley_problem", response_text)
            assert result.passed, f"Validation failed: {result.failures}"
    """
    from tests.sophia_validator import SophiaValidator

    return SophiaValidator("tests/sophia_specs.json")


def validate_sophia_compliance(
    prompt_id: str,
    response_text: str,
    sophia_validator
) -> Dict[str, Any]:
    """Validate response against Sophia specifications.

    Args:
        prompt_id: The prompt identifier
        response_text: The LLM response to validate
        sophia_validator: The SophiaValidator fixture

    Returns:
        dict with keys: passed (bool), failures (list), metrics (dict)
    """
    result = sophia_validator.validate_response(prompt_id, response_text)

    return {
        "passed": result.passed,
        "failures": result.failures,
        "metrics": {
            "checks_passed": result.passed_checks,
            "checks_total": result.total_checks,
            "word_count": result.response_length,
            "pass_rate": result.passed_checks / result.total_checks if result.total_checks > 0 else 0.0
        }
    }


# ---------------------------------------------------------------------------
# Authentication and Authorization Mock Fixtures (Task 3.3)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_auth_token():
    """Generate a simple test JWT token string for Authorization headers.

    Example usage:
        def test_protected_endpoint(test_client, mock_auth_token):
            response = test_client.get(
                "/users/me",
                headers={"Authorization": f"Bearer {mock_auth_token}"}
            )
    """
    return "test_token_12345"


@pytest.fixture
def mock_user_free_tier(auth_mock_helper: AuthMockHelper):
    """Mock user with free tier subscription using AuthMockHelper.

    Uses AuthMockHelper to create a properly configured User object with
    free tier subscription attributes.

    Example usage:
        def test_free_user_access(mock_user_free_tier):
            assert mock_user_free_tier.subscription_tier == SubscriptionTier.FREE
            assert mock_user_free_tier.stripe_customer_id is None
    """
    from app.core.db_models import SubscriptionTier, SubscriptionStatus

    # Use AuthMockHelper to create base user
    user = auth_mock_helper.create_test_user(
        user_id=1,
        username="freeuser",
        email="free@test.com",
        role="user"
    )

    # Add subscription attributes
    user.subscription_tier = SubscriptionTier.FREE
    user.subscription_status = SubscriptionStatus.ACTIVE
    user.stripe_customer_id = None

    return user


@pytest.fixture
def mock_user_premium_tier(auth_mock_helper: AuthMockHelper):
    """Mock user with premium tier subscription using AuthMockHelper.

    Uses AuthMockHelper to create a properly configured User object with
    premium tier subscription attributes.

    Example usage:
        def test_premium_user_access(mock_user_premium_tier):
            assert mock_user_premium_tier.subscription_tier == SubscriptionTier.PREMIUM
            assert mock_user_premium_tier.stripe_customer_id == "cus_premium123"
    """
    from app.core.db_models import SubscriptionTier, SubscriptionStatus

    # Use AuthMockHelper to create premium user
    user = auth_mock_helper.create_premium_user(
        user_id=2,
        username="premiumuser",
        email="premium@test.com"
    )

    # Add subscription attributes
    user.subscription_tier = SubscriptionTier.PREMIUM
    user.subscription_status = SubscriptionStatus.ACTIVE
    user.stripe_customer_id = "cus_premium123"

    return user


@pytest.fixture
def mock_user_admin(auth_mock_helper: AuthMockHelper):
    """Mock admin user with superuser privileges using AuthMockHelper.

    Uses AuthMockHelper to create a properly configured admin User object
    with premium tier subscription.

    Example usage:
        def test_admin_access(mock_user_admin):
            assert mock_user_admin.is_superuser is True
    """
    from app.core.db_models import SubscriptionTier, SubscriptionStatus

    # Use AuthMockHelper to create admin user
    user = auth_mock_helper.create_admin_user(
        user_id=999,
        username="admin",
        email="admin@test.com"
    )

    # Add subscription attributes
    user.subscription_tier = SubscriptionTier.PREMIUM
    user.subscription_status = SubscriptionStatus.ACTIVE
    user.stripe_customer_id = "cus_admin123"

    return user


@pytest.fixture
async def mock_auth_service_with_user(test_resource_manager: TestResourceManager, mock_user_free_tier):
    """Mock AuthService configured with a test user.

    Provides an AsyncMock for AuthService with common methods configured
    to return appropriate values for an authenticated user context.

    Example usage:
        async def test_with_auth_service(mock_auth_service_with_user):
            user_context = await mock_auth_service_with_user.get_user_context("test_token")
            assert user_context["authenticated"] is True
    """
    mock_auth_service = AsyncMock()

    # Configure get_user_context
    mock_auth_service.get_user_context.return_value = {
        "authenticated": True,
        "user_id": mock_user_free_tier.id,
        "features": [],
        "session_id": "test_session_123"
    }

    # Configure create_anonymous_session
    mock_auth_service.create_anonymous_session.return_value = "test_session_id"

    # Configure get_available_providers
    mock_auth_service.get_available_providers.return_value = {}

    # Configure delete_session
    mock_auth_service.delete_session.return_value = True

    # Register for cleanup
    test_resource_manager.register_mock("mock_auth_service", mock_auth_service)

    return mock_auth_service


@pytest.fixture
def make_authenticated_request(test_client: TestClient, mock_auth_token):
    """Helper fixture to make authenticated API requests.

    Returns a function that adds Authorization header with Bearer token
    to requests made through the test client.

    Example usage:
        def test_protected_endpoint(make_authenticated_request):
            response = make_authenticated_request("get", "/users/me")
            assert response.status_code == 200

            # With additional kwargs
            response = make_authenticated_request(
                "post",
                "/papers",
                json={"title": "Test Paper"}
            )
    """
    def _make_request(method: str, path: str, **kwargs):
        """Make an authenticated request.

        Args:
            method: HTTP method (get, post, put, delete, etc.)
            path: Request path
            **kwargs: Additional arguments to pass to the request method

        Returns:
            Response object
        """
        # Add Authorization header
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {mock_auth_token}"
        kwargs["headers"] = headers

        # Call the appropriate method on test_client
        client_method = getattr(test_client, method.lower())
        return client_method(path, **kwargs)

    return _make_request


@pytest.fixture
def override_auth_dependency(test_client: TestClient):
    """Helper fixture to override auth dependencies for testing different user contexts.

    Returns a context manager function that temporarily overrides authentication
    dependencies with a mock user.

    Example usage:
        def test_with_different_users(override_auth_dependency, mock_user_premium_tier):
            with override_auth_dependency(mock_user_premium_tier):
                response = test_client.get("/premium-feature")
                assert response.status_code == 200
    """
    from contextlib import contextmanager

    @contextmanager
    def _override_auth(mock_user):
        """Override auth dependency with mock user.

        Args:
            mock_user: Mock user object to use for authentication

        Yields:
            None
        """
        # Import actual auth dependencies from auth_config
        from app.core.auth_config import current_active_user, current_user_optional

        # Save original overrides
        original_overrides = test_client.app.dependency_overrides.copy()

        # Override auth dependencies with the actual fastapi-users dependencies
        test_client.app.dependency_overrides[current_active_user] = lambda: mock_user
        test_client.app.dependency_overrides[current_user_optional] = lambda: mock_user

        try:
            yield
        finally:
            # Restore original overrides
            test_client.app.dependency_overrides = original_overrides

            # Clear any auth state
            if hasattr(test_client.app.state, 'user'):
                delattr(test_client.app.state, 'user')

    return _override_auth


# ---------------------------------------------------------------------------
# Payment testing fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def payment_settings(mock_environment):
    """Get payment settings for testing with environment mocks applied.

    This fixture provides settings with payments enabled but without requiring
    real Stripe API keys. Tests can mock Stripe calls as needed.
    """
    from app.config.settings import get_settings
    settings = get_settings()
    # Force payments enabled for testing
    settings.payments_enabled = True
    return settings


@pytest.fixture
def mock_cache_service():
    """Mock cache service for payment service testing."""
    from unittest.mock import AsyncMock
    cache = AsyncMock()
    cache.get.return_value = None
    cache.set.return_value = True
    cache.delete.return_value = True
    cache._make_cache_key = lambda *args: ":".join(map(str, args))
    return cache


@pytest.fixture
def mock_stripe_customer():
    """Mock Stripe customer object for payment tests."""
    from unittest.mock import MagicMock
    customer = MagicMock()
    customer.id = "cus_test1234567890"
    customer.email = "test@example.com"
    customer.created = 1234567890
    customer.metadata = {}
    return customer


@pytest.fixture
def mock_stripe_subscription():
    """Mock Stripe subscription object for payment tests."""
    from unittest.mock import MagicMock
    subscription = MagicMock()
    subscription.id = "sub_test123"
    subscription.customer = "cus_test1234567890"
    subscription.status = "active"
    subscription.current_period_start = 1234567890
    subscription.current_period_end = 1234567890 + 2592000  # +30 days
    subscription.items = MagicMock()
    subscription.items.data = [MagicMock(price=MagicMock(id="price_test123"))]
    return subscription


@pytest.fixture
def mock_stripe_checkout_session():
    """Mock Stripe checkout session object for payment tests."""
    from unittest.mock import MagicMock
    session = MagicMock()
    session.id = "cs_test123"
    session.url = "https://checkout.stripe.com/pay/cs_test123"
    session.customer = "cus_test1234567890"
    session.subscription = "sub_test123"
    return session


@pytest.fixture
def mock_user():
    """Mock user object for testing."""
    from unittest.mock import MagicMock
    from app.core.user_models import User
    from app.core.db_models import SubscriptionTier, SubscriptionStatus
    
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "test@example.com"
    user.stripe_customer_id = None
    user.subscription_tier = SubscriptionTier.FREE
    user.subscription_status = SubscriptionStatus.ACTIVE
    return user


@pytest.fixture
def mock_stripe_api():
    """Comprehensive Stripe API mocking for payment tests."""
    from unittest.mock import MagicMock, AsyncMock
    import json
    import hmac
    import hashlib
    from datetime import datetime, timedelta
    
    class MockStripeAPI:
        """Mock Stripe API with realistic responses and error simulation."""
        
        def __init__(self):
            self.customers = {}
            self.subscriptions = {}
            self.checkout_sessions = {}
            self.payment_intents = {}
            self.refunds = {}
            self.disputes = {}
            self.webhooks = {}
            
        def create_customer(self, **kwargs):
            """Mock Stripe customer creation."""
            customer_id = f"cus_mock_{len(self.customers) + 1}"
            customer = MagicMock()
            customer.id = customer_id
            customer.email = kwargs.get('email', 'test@example.com')
            customer.name = kwargs.get('name', 'Test User')
            customer.created = int(datetime.utcnow().timestamp())
            customer.metadata = kwargs.get('metadata', {})
            self.customers[customer_id] = customer
            return customer
            
        def create_subscription(self, **kwargs):
            """Mock Stripe subscription creation."""
            sub_id = f"sub_mock_{len(self.subscriptions) + 1}"
            subscription = MagicMock()
            subscription.id = sub_id
            subscription.customer = kwargs.get('customer', 'cus_mock_1')
            subscription.status = 'active'
            subscription.current_period_start = int(datetime.utcnow().timestamp())
            subscription.current_period_end = int((datetime.utcnow() + timedelta(days=30)).timestamp())
            subscription.items = MagicMock()
            subscription.items.data = [
                MagicMock(price=MagicMock(id=kwargs.get('items', [{}])[0].get('price', 'price_mock_1')))
            ]
            subscription.cancel_at_period_end = False
            subscription.metadata = kwargs.get('metadata', {})
            self.subscriptions[sub_id] = subscription
            return subscription
            
        def create_checkout_session(self, **kwargs):
            """Mock Stripe checkout session creation."""
            session_id = f"cs_mock_{len(self.checkout_sessions) + 1}"
            session = MagicMock()
            session.id = session_id
            session.url = f"https://checkout.stripe.com/pay/{session_id}"
            session.customer = kwargs.get('customer')
            session.subscription = None
            session.payment_status = 'unpaid'
            session.status = 'open'
            session.metadata = kwargs.get('metadata', {})
            self.checkout_sessions[session_id] = session
            return session
            
        def create_refund(self, **kwargs):
            """Mock Stripe refund creation."""
            refund_id = f"re_mock_{len(self.refunds) + 1}"
            refund = MagicMock()
            refund.id = refund_id
            refund.amount = kwargs.get('amount', 1000)
            refund.currency = kwargs.get('currency', 'usd')
            refund.status = 'succeeded'
            refund.payment_intent = kwargs.get('payment_intent', 'pi_mock_1')
            refund.charge = f"ch_mock_{len(self.refunds) + 1}"
            refund.reason = kwargs.get('reason', 'requested_by_customer')
            refund.receipt_number = f"receipt_{refund_id}"
            refund.created = int(datetime.utcnow().timestamp())
            refund.metadata = kwargs.get('metadata', {})
            self.refunds[refund_id] = refund
            return refund
            
        def retrieve_customer(self, customer_id):
            """Mock Stripe customer retrieval."""
            if customer_id in self.customers:
                return self.customers[customer_id]
            raise MockStripeError("No such customer: " + customer_id)
            
        def retrieve_subscription(self, subscription_id):
            """Mock Stripe subscription retrieval."""
            if subscription_id in self.subscriptions:
                return self.subscriptions[subscription_id]
            raise MockStripeError("No such subscription: " + subscription_id)
            
        def modify_subscription(self, subscription_id, **kwargs):
            """Mock Stripe subscription modification."""
            if subscription_id in self.subscriptions:
                subscription = self.subscriptions[subscription_id]
                if kwargs.get('cancel_at_period_end'):
                    subscription.cancel_at_period_end = True
                    subscription.status = 'active'  # Still active until period end
                return subscription
            raise MockStripeError("No such subscription: " + subscription_id)
            
        def delete_subscription(self, subscription_id):
            """Mock Stripe subscription deletion (immediate cancellation)."""
            if subscription_id in self.subscriptions:
                subscription = self.subscriptions[subscription_id]
                subscription.status = 'canceled'
                return subscription
            raise MockStripeError("No such subscription: " + subscription_id)
            
        def construct_webhook_event(self, payload, signature, secret):
            """Mock Stripe webhook event construction with signature validation."""
            # Simple signature validation mock
            if not signature or not signature.startswith('t='):
                raise MockStripeError("Invalid signature format")
                
            try:
                event_data = json.loads(payload)
                return event_data
            except json.JSONDecodeError:
                raise MockStripeError("Invalid JSON payload")
                
        def simulate_webhook_signature(self, payload, secret="whsec_test_secret"):
            """Generate a mock webhook signature for testing."""
            timestamp = str(int(datetime.utcnow().timestamp()))
            signed_payload = f"{timestamp}.{payload}"
            signature = hmac.new(
                secret.encode('utf-8'),
                signed_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            return f"t={timestamp},v1={signature}"
            
        def simulate_error(self, error_type="generic", message="Mock Stripe error"):
            """Simulate various Stripe API errors."""
            if error_type == "card_declined":
                raise MockCardError("Your card was declined.", "card_declined")
            elif error_type == "invalid_request":
                raise MockInvalidRequestError(message, None)
            elif error_type == "authentication":
                raise MockAuthenticationError("Invalid API key provided")
            elif error_type == "rate_limit":
                raise MockRateLimitError("Too many requests")
            else:
                raise MockStripeError(message)
    
    class MockStripeError(Exception):
        """Mock Stripe base error."""
        pass
        
    class MockCardError(MockStripeError):
        """Mock Stripe card error."""
        def __init__(self, message, code):
            super().__init__(message)
            self.code = code
            
    class MockInvalidRequestError(MockStripeError):
        """Mock Stripe invalid request error."""
        def __init__(self, message, param):
            super().__init__(message)
            self.param = param
            
    class MockAuthenticationError(MockStripeError):
        """Mock Stripe authentication error."""
        pass
        
    class MockRateLimitError(MockStripeError):
        """Mock Stripe rate limit error."""
        pass
    
    # Create mock Stripe API instance
    mock_api = MockStripeAPI()
    
    # Create mock Stripe module structure
    mock_stripe = MagicMock()
    mock_stripe.Customer.create = mock_api.create_customer
    mock_stripe.Customer.retrieve = mock_api.retrieve_customer
    mock_stripe.Subscription.create = mock_api.create_subscription
    mock_stripe.Subscription.retrieve = mock_api.retrieve_subscription
    mock_stripe.Subscription.modify = mock_api.modify_subscription
    mock_stripe.Subscription.delete = mock_api.delete_subscription
    mock_stripe.checkout.Session.create = mock_api.create_checkout_session
    mock_stripe.Refund.create = mock_api.create_refund
    mock_stripe.Webhook.construct_event = mock_api.construct_webhook_event
    
    # Add error classes
    mock_stripe.error.StripeError = MockStripeError
    mock_stripe.error.CardError = MockCardError
    mock_stripe.error.InvalidRequestError = MockInvalidRequestError
    mock_stripe.error.AuthenticationError = MockAuthenticationError
    mock_stripe.error.RateLimitError = MockRateLimitError
    
    # Add API instance for advanced testing
    mock_stripe._api = mock_api
    
    return mock_stripe


@pytest.fixture
def stripe_webhook_validator():
    """Stripe webhook signature validator for testing."""
    import hmac
    import hashlib
    from datetime import datetime
    
    def create_valid_signature(payload, secret="whsec_test_secret"):
        """Create a valid Stripe webhook signature."""
        timestamp = str(int(datetime.utcnow().timestamp()))
        signed_payload = f"{timestamp}.{payload}"
        signature = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"t={timestamp},v1={signature}"
        
    def create_invalid_signature():
        """Create an invalid Stripe webhook signature."""
        return "t=invalid,v1=invalid_signature"
        
    return {
        'create_valid_signature': create_valid_signature,
        'create_invalid_signature': create_invalid_signature
    }


@pytest.fixture
def stripe_error_simulator(mock_stripe_api):
    """Stripe API error simulation for testing error handling."""
    
    def simulate_customer_creation_error(error_type="card_declined"):
        """Simulate customer creation errors."""
        def error_side_effect(*args, **kwargs):
            mock_stripe_api._api.simulate_error(error_type)
        return error_side_effect
        
    def simulate_subscription_error(error_type="invalid_request"):
        """Simulate subscription operation errors."""
        def error_side_effect(*args, **kwargs):
            mock_stripe_api._api.simulate_error(error_type)
        return error_side_effect
        
    def simulate_webhook_error(error_type="invalid_signature"):
        """Simulate webhook processing errors."""
        def error_side_effect(*args, **kwargs):
            if error_type == "invalid_signature":
                raise mock_stripe_api.error.StripeError("Invalid signature")
            elif error_type == "invalid_payload":
                raise ValueError("Invalid payload")
            else:
                mock_stripe_api._api.simulate_error(error_type)
        return error_side_effect
        
    def simulate_network_error():
        """Simulate network-related errors."""
        import socket
        def error_side_effect(*args, **kwargs):
            raise socket.timeout("Network timeout")
        return error_side_effect
        
    return {
        'customer_creation_error': simulate_customer_creation_error,
        'subscription_error': simulate_subscription_error,
        'webhook_error': simulate_webhook_error,
        'network_error': simulate_network_error
    }


@pytest.fixture
async def mock_payment_service():
    """Mock payment service for testing without Stripe."""
    from unittest.mock import AsyncMock, MagicMock
    service = MagicMock()
    service.create_checkout_session = AsyncMock(return_value={
        "id": "cs_test_123",
        "url": "https://checkout.stripe.com/test"
    })
    service.get_subscription = AsyncMock(return_value=None)
    service.cancel_subscription = AsyncMock(return_value=True)
    service.create_customer = AsyncMock(return_value="cus_test_123")
    service.is_enabled = True
    return service


@pytest.fixture
async def mock_subscription_manager():
    """Mock subscription manager for testing."""
    from unittest.mock import AsyncMock, MagicMock
    from app.core.db_models import SubscriptionTier, SubscriptionStatus

    manager = MagicMock()
    manager.get_user_subscription = AsyncMock(return_value=MagicMock(
        tier=SubscriptionTier.FREE,
        status=SubscriptionStatus.ACTIVE,
        requests_used=0,
        requests_limit=2000
    ))
    manager.check_rate_limit = AsyncMock(return_value=True)
    manager.increment_usage = AsyncMock(return_value=None)
    return manager


@pytest.fixture
async def mock_billing_service():
    """Mock billing service for testing."""
    from unittest.mock import AsyncMock, MagicMock

    service = MagicMock()
    service.get_billing_history = AsyncMock(return_value=[])
    service.get_usage_stats = AsyncMock(return_value={
        "current_period_start": "2024-01-01",
        "current_period_end": "2024-02-01",
        "requests_used": 100,
        "requests_limit": 2000
    })
    return service


@pytest.fixture
async def async_session(mock_db_session):
    """Provide async database session for timestamp behavior tests."""
    # Return the mock database session fixture
    return mock_db_session
