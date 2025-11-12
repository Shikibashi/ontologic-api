"""
Database session mock management system.

Provides comprehensive database session mocking with proper method signatures,
transaction rollback simulation, and query result mocking for test isolation.
"""

import asyncio
from typing import Any, Dict, List, Optional, Union, Callable, Type, Sequence
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select, Insert, Update, Delete
from sqlalchemy.engine import Result, ScalarResult
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError

from app.core.db_models import ChatConversation, ChatMessage, Subscription, PaymentRecord
from app.core.user_models import User


class DatabaseMockManager:
    """
    Comprehensive database session mock management with proper SQLAlchemy patterns.
    
    Provides realistic database session mocks with proper method signatures,
    transaction handling, and query result simulation for test isolation.
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, AsyncMock] = {}
        self.session_configs: Dict[str, Dict[str, Any]] = {}
        self.query_results: Dict[str, Dict[str, Any]] = {}
        self.transaction_states: Dict[str, str] = {}  # "active", "committed", "rolled_back"
    
    def create_async_session_mock(
        self,
        session_id: str = "default",
        autocommit: bool = False,
        autoflush: bool = True,
        expire_on_commit: bool = True
    ) -> AsyncMock:
        """
        Create AsyncSession mock with proper SQLAlchemy method signatures.
        
        Args:
            session_id: Unique identifier for this session
            autocommit: Whether to auto-commit transactions
            autoflush: Whether to auto-flush before queries
            expire_on_commit: Whether to expire objects on commit
        
        Returns:
            AsyncMock configured as AsyncSession with proper signatures
        """
        session_mock = AsyncMock(spec=AsyncSession)
        
        # Configure session properties
        session_mock.autocommit = autocommit
        session_mock.autoflush = autoflush
        session_mock.expire_on_commit = expire_on_commit
        session_mock.is_active = True
        session_mock.in_transaction = MagicMock(return_value=True)
        
        # Configure transaction methods
        session_mock.commit = AsyncMock()
        session_mock.rollback = AsyncMock()
        session_mock.close = AsyncMock()
        session_mock.begin = AsyncMock()
        
        # Configure query execution methods
        session_mock.execute = AsyncMock()
        session_mock.scalar = AsyncMock()
        session_mock.scalars = AsyncMock()
        session_mock.stream = AsyncMock()
        session_mock.stream_scalars = AsyncMock()
        
        # Configure object manipulation methods
        session_mock.get = AsyncMock()
        session_mock.get_one = AsyncMock()
        session_mock.merge = AsyncMock()
        session_mock.refresh = AsyncMock()
        session_mock.expunge = MagicMock()  # Sync method
        session_mock.expunge_all = MagicMock()  # Sync method
        session_mock.add = MagicMock()  # Sync method
        session_mock.add_all = MagicMock()  # Sync method
        session_mock.delete = AsyncMock()
        session_mock.flush = AsyncMock()
        
        # Configure context manager behavior
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock()
        
        # Configure transaction state tracking
        self.transaction_states[session_id] = "active"
        
        # Add custom behavior for transaction methods
        async def commit_side_effect():
            self.transaction_states[session_id] = "committed"
            if expire_on_commit:
                # Simulate object expiration
                pass
        
        async def rollback_side_effect():
            self.transaction_states[session_id] = "rolled_back"
            # Reset any pending changes
            self._reset_session_state(session_id)
        
        async def close_side_effect():
            self.transaction_states[session_id] = "closed"
            session_mock.is_active = False
        
        session_mock.commit.side_effect = commit_side_effect
        session_mock.rollback.side_effect = rollback_side_effect
        session_mock.close.side_effect = close_side_effect
        
        # Store session configuration
        self.session_configs[session_id] = {
            "autocommit": autocommit,
            "autoflush": autoflush,
            "expire_on_commit": expire_on_commit
        }
        
        # Track session
        self.active_sessions[session_id] = session_mock
        
        return session_mock
    
    def configure_query_results(
        self,
        session_id: str,
        method_name: str,
        results: Union[Any, List[Any], Callable]
    ):
        """
        Configure query results for a specific session and method.
        
        Args:
            session_id: Session identifier
            method_name: Query method name (execute, scalar, scalars, etc.)
            results: Results to return (single value, list, or callable)
        """
        if session_id not in self.query_results:
            self.query_results[session_id] = {}
        
        session_mock = self.active_sessions.get(session_id)
        if not session_mock:
            raise ValueError(f"Session {session_id} not found")
        
        method_mock = getattr(session_mock, method_name)
        
        if callable(results):
            method_mock.side_effect = results
        elif isinstance(results, list):
            if len(results) == 1:
                method_mock.return_value = results[0]
            else:
                method_mock.side_effect = results
        else:
            method_mock.return_value = results
        
        self.query_results[session_id][method_name] = results
    
    def create_result_mock(
        self,
        rows: List[Any] = None,
        scalar_result: Any = None,
        rowcount: int = 0
    ) -> MagicMock:
        """
        Create a SQLAlchemy Result mock.
        
        Args:
            rows: List of row objects to return
            scalar_result: Single scalar value to return
            rowcount: Number of affected rows
        
        Returns:
            MagicMock configured as SQLAlchemy Result
        """
        result_mock = MagicMock(spec=Result)
        
        # Configure result properties
        result_mock.rowcount = rowcount
        result_mock.returns_rows = bool(rows)
        
        # Configure result methods
        if rows:
            result_mock.fetchall = MagicMock(return_value=rows)
            result_mock.fetchone = MagicMock(return_value=rows[0] if rows else None)
            result_mock.fetchmany = MagicMock(return_value=rows)
            result_mock.all = MagicMock(return_value=rows)
            result_mock.first = MagicMock(return_value=rows[0] if rows else None)
            result_mock.one = MagicMock(return_value=rows[0] if rows else None)
            result_mock.one_or_none = MagicMock(return_value=rows[0] if rows else None)
            result_mock.scalar = MagicMock(return_value=scalar_result or (rows[0] if rows else None))
            result_mock.scalar_one = MagicMock(return_value=scalar_result or (rows[0] if rows else None))
            result_mock.scalar_one_or_none = MagicMock(return_value=scalar_result or (rows[0] if rows else None))
        else:
            result_mock.fetchall = MagicMock(return_value=[])
            result_mock.fetchone = MagicMock(return_value=None)
            result_mock.fetchmany = MagicMock(return_value=[])
            result_mock.all = MagicMock(return_value=[])
            result_mock.first = MagicMock(return_value=None)
            result_mock.one = MagicMock(side_effect=SQLAlchemyError("No row found"))
            result_mock.one_or_none = MagicMock(return_value=None)
            result_mock.scalar = MagicMock(return_value=scalar_result)
            result_mock.scalar_one = MagicMock(side_effect=SQLAlchemyError("No row found") if scalar_result is None else None)
            result_mock.scalar_one_or_none = MagicMock(return_value=scalar_result)
        
        return result_mock
    
    def create_scalar_result_mock(self, values: List[Any] = None) -> MagicMock:
        """
        Create a SQLAlchemy ScalarResult mock.
        
        Args:
            values: List of scalar values to return
        
        Returns:
            MagicMock configured as SQLAlchemy ScalarResult
        """
        scalar_result_mock = MagicMock(spec=ScalarResult)
        
        if values:
            scalar_result_mock.all = MagicMock(return_value=values)
            scalar_result_mock.first = MagicMock(return_value=values[0] if values else None)
            scalar_result_mock.one = MagicMock(return_value=values[0] if values else None)
            scalar_result_mock.one_or_none = MagicMock(return_value=values[0] if values else None)
        else:
            scalar_result_mock.all = MagicMock(return_value=[])
            scalar_result_mock.first = MagicMock(return_value=None)
            scalar_result_mock.one = MagicMock(side_effect=SQLAlchemyError("No row found"))
            scalar_result_mock.one_or_none = MagicMock(return_value=None)
        
        return scalar_result_mock
    
    def simulate_transaction_rollback(self, session_id: str):
        """
        Simulate transaction rollback for test isolation.
        
        Args:
            session_id: Session identifier to rollback
        """
        if session_id not in self.active_sessions:
            return
        
        session_mock = self.active_sessions[session_id]
        
        # Reset method call counts
        session_mock.reset_mock()
        
        # Update transaction state
        self.transaction_states[session_id] = "rolled_back"
        
        # Reset query results to simulate rollback
        self._reset_session_state(session_id)
    
    def simulate_database_error(
        self,
        session_id: str,
        method_name: str,
        error_type: Type[Exception] = SQLAlchemyError,
        error_message: str = "Database error"
    ):
        """
        Simulate database errors for error handling tests.
        
        Args:
            session_id: Session identifier
            method_name: Method to configure with error
            error_type: Type of exception to raise
            error_message: Error message
        """
        if session_id not in self.active_sessions:
            return
        
        session_mock = self.active_sessions[session_id]
        method_mock = getattr(session_mock, method_name)
        method_mock.side_effect = error_type(error_message)
    
    def create_session_factory_mock(self, session_mock: AsyncMock) -> MagicMock:
        """
        Create a session factory mock (like AsyncSessionLocal).
        
        Args:
            session_mock: Session mock to return from factory
        
        Returns:
            MagicMock configured as session factory
        """
        factory_mock = MagicMock()
        factory_mock.return_value = session_mock
        factory_mock.__call__ = MagicMock(return_value=session_mock)
        
        # Configure as async context manager
        @asynccontextmanager
        async def async_context():
            try:
                yield session_mock
            except Exception:
                await session_mock.rollback()
                raise
            else:
                await session_mock.commit()
            finally:
                await session_mock.close()
        
        factory_mock.__call__ = MagicMock(return_value=async_context())
        
        return factory_mock
    
    def create_engine_mock(self) -> AsyncMock:
        """
        Create an AsyncEngine mock.
        
        Returns:
            AsyncMock configured as AsyncEngine
        """
        engine_mock = AsyncMock(spec=AsyncEngine)
        
        # Configure engine methods
        engine_mock.dispose = AsyncMock()
        engine_mock.begin = AsyncMock()
        engine_mock.connect = AsyncMock()
        engine_mock.execute = AsyncMock()
        
        return engine_mock
    
    def _reset_session_state(self, session_id: str):
        """Reset session state for rollback simulation."""
        if session_id in self.query_results:
            # Clear cached query results
            self.query_results[session_id].clear()
    
    async def cleanup_all_sessions(self):
        """Clean up all active session mocks."""
        for session_id, session_mock in self.active_sessions.items():
            try:
                if self.transaction_states.get(session_id) == "active":
                    await session_mock.rollback()
                await session_mock.close()
            except Exception:
                pass
        
        self.active_sessions.clear()
        self.session_configs.clear()
        self.query_results.clear()
        self.transaction_states.clear()
    
    # Convenience methods for common database operations
    
    def setup_chat_message_queries(
        self,
        session_id: str,
        messages: List[ChatMessage] = None
    ):
        """Setup common chat message query results."""
        messages = messages or []
        
        # Configure execute method for SELECT queries
        result_mock = self.create_result_mock(rows=messages)
        self.configure_query_results(session_id, "execute", result_mock)
        
        # Configure scalar methods
        if messages:
            self.configure_query_results(session_id, "scalar", messages[0])
            scalar_result_mock = self.create_scalar_result_mock([msg.id for msg in messages])
            self.configure_query_results(session_id, "scalars", scalar_result_mock)
        else:
            self.configure_query_results(session_id, "scalar", None)
            self.configure_query_results(session_id, "scalars", self.create_scalar_result_mock([]))
    
    def setup_user_queries(
        self,
        session_id: str,
        users: List[User] = None
    ):
        """Setup common user query results."""
        users = users or []
        
        result_mock = self.create_result_mock(rows=users)
        self.configure_query_results(session_id, "execute", result_mock)
        
        if users:
            self.configure_query_results(session_id, "get", users[0])
            self.configure_query_results(session_id, "scalar", users[0])
        else:
            self.configure_query_results(session_id, "get", None)
            self.configure_query_results(session_id, "scalar", None)
    
    def setup_subscription_queries(
        self,
        session_id: str,
        subscriptions: List[Subscription] = None
    ):
        """Setup common subscription query results."""
        subscriptions = subscriptions or []
        
        result_mock = self.create_result_mock(rows=subscriptions)
        self.configure_query_results(session_id, "execute", result_mock)
        
        if subscriptions:
            self.configure_query_results(session_id, "scalar", subscriptions[0])
        else:
            self.configure_query_results(session_id, "scalar", None)


# Convenience functions for common database mocking patterns

def create_test_database_session(
    session_id: str = "test",
    with_chat_data: bool = False,
    with_user_data: bool = False,
    with_subscription_data: bool = False
) -> AsyncMock:
    """
    Create a test database session with common data setup.
    
    Args:
        session_id: Session identifier
        with_chat_data: Whether to setup chat message data
        with_user_data: Whether to setup user data
        with_subscription_data: Whether to setup subscription data
    
    Returns:
        AsyncMock configured as database session
    """
    manager = DatabaseMockManager()
    session_mock = manager.create_async_session_mock(session_id)
    
    if with_chat_data:
        manager.setup_chat_message_queries(session_id, [])
    
    if with_user_data:
        manager.setup_user_queries(session_id, [])
    
    if with_subscription_data:
        manager.setup_subscription_queries(session_id, [])
    
    return session_mock


def patch_database_session(session_mock: AsyncMock):
    """
    Patch database session dependencies with the provided mock.
    
    Args:
        session_mock: Session mock to use
    
    Returns:
        List of patch objects
    """
    patches = [
        patch("app.core.database.AsyncSessionLocal", return_value=session_mock),
        patch("app.core.dependencies.get_db_session", return_value=session_mock),
    ]
    
    return patches