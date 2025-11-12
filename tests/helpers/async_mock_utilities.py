"""
Async-aware service mocking utilities.

Provides utilities for creating proper async mocks, context managers,
and session lifecycle management for database operations.
"""

import asyncio
from typing import Any, Dict, List, Optional, Type, Union, Callable, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session


class AsyncMockUtilities:
    """
    Utilities for creating async-aware mocks with proper lifecycle management.
    """
    
    @staticmethod
    def create_async_service_mock(service_class: Type, **method_configs) -> AsyncMock:
        """
        Create an async-aware mock for a service class.
        
        Args:
            service_class: The service class to mock
            **method_configs: Configuration for specific methods
                - method_name: return_value or side_effect
        
        Returns:
            AsyncMock configured for the service class
        """
        mock = AsyncMock(spec=service_class)
        
        # Configure methods based on provided configs
        for method_name, config in method_configs.items():
            if hasattr(mock, method_name):
                method_mock = getattr(mock, method_name)
                if isinstance(config, dict):
                    if "return_value" in config:
                        method_mock.return_value = config["return_value"]
                    if "side_effect" in config:
                        method_mock.side_effect = config["side_effect"]
                else:
                    method_mock.return_value = config
        
        return mock
    
    @staticmethod
    def create_async_context_manager_mock(return_value: Any = None) -> AsyncMock:
        """
        Create an async context manager mock.
        
        Args:
            return_value: Value to return from __aenter__
        
        Returns:
            AsyncMock configured as async context manager
        """
        mock = AsyncMock()
        mock.__aenter__ = AsyncMock(return_value=return_value or mock)
        mock.__aexit__ = AsyncMock(return_value=None)
        return mock
    
    @staticmethod
    def create_async_generator_mock(values: List[Any]) -> AsyncMock:
        """
        Create an async generator mock.
        
        Args:
            values: List of values to yield
        
        Returns:
            AsyncMock that yields the provided values
        """
        async def async_generator():
            for value in values:
                yield value
        
        mock = AsyncMock()
        mock.__aiter__ = AsyncMock(return_value=async_generator())
        return mock
    
    @staticmethod
    def create_coroutine_mock(return_value: Any = None, side_effect: Any = None) -> AsyncMock:
        """
        Create a coroutine mock that can be awaited.
        
        Args:
            return_value: Value to return when awaited
            side_effect: Side effect when awaited
        
        Returns:
            AsyncMock configured as coroutine
        """
        mock = AsyncMock()
        if return_value is not None:
            mock.return_value = return_value
        if side_effect is not None:
            mock.side_effect = side_effect
        return mock
    
    @staticmethod
    def patch_async_method(target: str, return_value: Any = None, side_effect: Any = None):
        """
        Create a patch for an async method.
        
        Args:
            target: Target method to patch (e.g., "app.services.service.method")
            return_value: Return value for the mock
            side_effect: Side effect for the mock
        
        Returns:
            Patch object for the async method
        """
        mock = AsyncMock()
        if return_value is not None:
            mock.return_value = return_value
        if side_effect is not None:
            mock.side_effect = side_effect
        
        return patch(target, mock)
    
    @staticmethod
    def create_async_callable_mock(return_value: Any = None) -> AsyncMock:
        """
        Create an async callable mock.
        
        Args:
            return_value: Value to return when called
        
        Returns:
            AsyncMock that can be called as async function
        """
        async def async_callable(*args, **kwargs):
            return return_value
        
        mock = AsyncMock(side_effect=async_callable)
        return mock


class AsyncSessionLifecycleManager:
    """
    Manager for async database session lifecycle in tests.
    
    Provides utilities for creating, managing, and cleaning up
    async database sessions with proper transaction handling.
    """
    
    def __init__(self):
        self.active_sessions: List[AsyncMock] = []
        self.session_configs: Dict[str, Dict[str, Any]] = {}
    
    def create_async_session_mock(
        self,
        session_name: str = "default",
        autocommit: bool = False,
        rollback_on_close: bool = True,
        **query_configs
    ) -> AsyncMock:
        """
        Create an async database session mock with proper lifecycle.
        
        Args:
            session_name: Name for the session (for tracking)
            autocommit: Whether to auto-commit transactions
            rollback_on_close: Whether to rollback on session close
            **query_configs: Configuration for query methods
        
        Returns:
            AsyncMock configured as AsyncSession
        """
        session_mock = AsyncMock(spec=AsyncSession)
        
        # Configure basic session methods
        session_mock.commit = AsyncMock()
        session_mock.rollback = AsyncMock()
        session_mock.close = AsyncMock()
        session_mock.refresh = AsyncMock()
        session_mock.flush = AsyncMock()
        session_mock.expunge = AsyncMock()
        session_mock.expunge_all = AsyncMock()
        
        # Configure query methods
        session_mock.execute = AsyncMock()
        session_mock.scalar = AsyncMock()
        session_mock.scalars = AsyncMock()
        session_mock.get = AsyncMock()
        session_mock.merge = AsyncMock()
        session_mock.add = MagicMock()  # Sync method
        session_mock.add_all = MagicMock()  # Sync method
        session_mock.delete = AsyncMock()
        
        # Configure query method return values
        for method_name, config in query_configs.items():
            if hasattr(session_mock, method_name):
                method_mock = getattr(session_mock, method_name)
                if isinstance(config, dict):
                    if "return_value" in config:
                        method_mock.return_value = config["return_value"]
                    if "side_effect" in config:
                        method_mock.side_effect = config["side_effect"]
                else:
                    method_mock.return_value = config
        
        # Configure context manager behavior
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock()
        
        # Store configuration
        self.session_configs[session_name] = {
            "autocommit": autocommit,
            "rollback_on_close": rollback_on_close
        }
        
        # Track session
        self.active_sessions.append(session_mock)
        
        return session_mock
    
    def create_session_factory_mock(self, session_mock: AsyncMock) -> AsyncMock:
        """
        Create a session factory mock that returns the provided session.
        
        Args:
            session_mock: The session mock to return
        
        Returns:
            AsyncMock configured as session factory
        """
        factory_mock = AsyncMock()
        factory_mock.return_value = session_mock
        factory_mock.__call__ = AsyncMock(return_value=session_mock)
        return factory_mock
    
    @asynccontextmanager
    async def async_session_context(self, session_mock: AsyncMock):
        """
        Async context manager for session lifecycle.
        
        Args:
            session_mock: The session mock to manage
        
        Yields:
            The session mock
        """
        try:
            yield session_mock
        except Exception:
            await session_mock.rollback()
            raise
        else:
            await session_mock.commit()
        finally:
            await session_mock.close()
    
    def simulate_transaction_rollback(self, session_mock: AsyncMock):
        """
        Simulate transaction rollback for test isolation.
        
        Args:
            session_mock: The session mock to rollback
        """
        # Reset all method call counts to simulate rollback
        session_mock.reset_mock()
        
        # Simulate rollback behavior
        session_mock.rollback.assert_called_once = MagicMock()
    
    def simulate_query_results(
        self,
        session_mock: AsyncMock,
        method_name: str,
        results: Union[Any, List[Any]]
    ):
        """
        Configure query results for a session mock.
        
        Args:
            session_mock: The session mock to configure
            method_name: The query method name (execute, scalar, etc.)
            results: The results to return
        """
        if hasattr(session_mock, method_name):
            method_mock = getattr(session_mock, method_name)
            if isinstance(results, list) and len(results) > 1:
                method_mock.side_effect = results
            else:
                method_mock.return_value = results[0] if isinstance(results, list) else results
    
    async def cleanup_all_sessions(self):
        """Clean up all active session mocks."""
        for session_mock in self.active_sessions:
            try:
                await session_mock.close()
            except Exception:
                pass
        
        self.active_sessions.clear()
        self.session_configs.clear()


class AsyncResourceManager:
    """
    Manager for async resources in tests with proper cleanup.
    """
    
    def __init__(self):
        self.async_resources: List[Any] = []
        self.cleanup_callbacks: List[Callable] = []
    
    def register_async_resource(self, resource: Any) -> Any:
        """Register an async resource for cleanup."""
        self.async_resources.append(resource)
        return resource
    
    def add_cleanup_callback(self, callback: Callable) -> None:
        """Add an async cleanup callback."""
        self.cleanup_callbacks.append(callback)
    
    async def cleanup_all(self):
        """Clean up all registered async resources."""
        # Execute cleanup callbacks
        for callback in self.cleanup_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                print(f"Warning: Async cleanup callback failed: {e}")
        
        # Close async resources
        for resource in self.async_resources:
            try:
                if hasattr(resource, 'aclose'):
                    await resource.aclose()
                elif hasattr(resource, 'close'):
                    if asyncio.iscoroutinefunction(resource.close):
                        await resource.close()
                    else:
                        resource.close()
            except Exception:
                pass
        
        self.async_resources.clear()
        self.cleanup_callbacks.clear()


# Convenience functions for common async mocking patterns

def create_async_service_mock_with_lifecycle(
    service_class: Type,
    start_return_value: Any = None,
    **method_configs
) -> AsyncMock:
    """
    Create async service mock with start/aclose lifecycle methods.
    
    Args:
        service_class: Service class to mock
        start_return_value: Return value for start() method
        **method_configs: Method configurations
    
    Returns:
        AsyncMock with lifecycle methods
    """
    mock = AsyncMockUtilities.create_async_service_mock(service_class, **method_configs)
    
    # Add lifecycle methods
    mock.start = AsyncMock(return_value=start_return_value or mock)
    mock.aclose = AsyncMock()
    
    return mock


def create_database_session_mock_with_queries(
    query_results: Dict[str, Any] = None
) -> AsyncMock:
    """
    Create database session mock with pre-configured query results.
    
    Args:
        query_results: Dictionary of method_name -> return_value
    
    Returns:
        AsyncMock configured as database session
    """
    manager = AsyncSessionLifecycleManager()
    return manager.create_async_session_mock(**(query_results or {}))


def patch_async_service_method(
    service_path: str,
    method_name: str,
    return_value: Any = None,
    side_effect: Any = None
):
    """
    Patch an async service method.
    
    Args:
        service_path: Path to service module
        method_name: Method name to patch
        return_value: Return value for mock
        side_effect: Side effect for mock
    
    Returns:
        Patch object
    """
    target = f"{service_path}.{method_name}"
    return AsyncMockUtilities.patch_async_method(target, return_value, side_effect)