"""
Authentication and authorization mock helpers.

Provides utilities for mocking authentication tokens, user objects,
and admin privileges for comprehensive auth testing.
"""

import uuid
import jwt
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.user_models import User
from enum import Enum

class UserRole(str, Enum):
    """User role enum for testing."""
    USER = "user"
    ADMIN = "admin"
    PREMIUM = "premium"
from app.core.db_models import Subscription, SubscriptionTier, SubscriptionStatus


class AuthMockHelper:
    """
    Helper class for creating authentication and authorization mocks.
    
    Provides utilities for generating test tokens, user objects,
    and mocking authentication dependencies.
    """
    
    def __init__(self):
        self.test_secret = "test-secret-key-for-jwt-signing"
        self.active_patches: List[Any] = []
        self.mock_users: Dict[str, User] = {}
    
    def create_test_user(
        self,
        user_id: int = None,
        username: str = "testuser",
        email: str = "test@example.com",
        role: Union[str, UserRole] = UserRole.USER,
        is_active: bool = True,
        **extra_fields
    ) -> User:
        """
        Create a test user object.
        
        Args:
            user_id: User ID (auto-generated if None)
            username: Username
            email: Email address
            role: User role (string or UserRole enum)
            is_active: Whether user is active
            **extra_fields: Additional user fields
        
        Returns:
            User object for testing
        """
        if user_id is None:
            user_id = len(self.mock_users) + 1
        
        if isinstance(role, str):
            role = UserRole(role)
        
        user_data = {
            "id": user_id,
            "username": username,
            "email": email,
            "hashed_password": "hashed_password_123",
            "is_active": is_active,
            "is_superuser": (role == UserRole.ADMIN),
            "is_verified": True,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            **extra_fields
        }
        
        user = User(**user_data)
        self.mock_users[str(user_id)] = user
        return user
    
    def create_admin_user(
        self,
        user_id: int = None,
        username: str = "admin",
        email: str = "admin@example.com"
    ) -> User:
        """Create a test admin user."""
        return self.create_test_user(
            user_id=user_id or 999,
            username=username,
            email=email,
            role=UserRole.ADMIN
        )
    
    def create_premium_user(
        self,
        user_id: int = None,
        username: str = "premium",
        email: str = "premium@example.com"
    ) -> User:
        """Create a test premium user."""
        return self.create_test_user(
            user_id=user_id or 888,
            username=username,
            email=email,
            role=UserRole.PREMIUM
        )
    
    def generate_jwt_token(
        self,
        user: User,
        expires_in_hours: int = 24,
        additional_claims: Dict[str, Any] = None
    ) -> str:
        """
        Generate a JWT token for a test user.
        
        Args:
            user: User object to generate token for
            expires_in_hours: Token expiration time in hours
            additional_claims: Additional JWT claims
        
        Returns:
            JWT token string
        """
        now = datetime.utcnow()
        exp = now + timedelta(hours=expires_in_hours)
        
        payload = {
            "sub": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_superuser": user.is_superuser,
            "is_active": user.is_active,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "iss": "ontologic-api-test",
            "aud": "ontologic-api"
        }
        
        if additional_claims:
            payload.update(additional_claims)
        
        return jwt.encode(payload, self.test_secret, algorithm="HS256")
    
    def generate_expired_token(self, user: User) -> str:
        """Generate an expired JWT token for testing."""
        return self.generate_jwt_token(user, expires_in_hours=-1)
    
    def generate_invalid_token(self) -> str:
        """Generate an invalid JWT token for testing."""
        return "invalid.jwt.token"
    
    def create_auth_headers(self, token: str) -> Dict[str, str]:
        """Create authorization headers with Bearer token."""
        return {"Authorization": f"Bearer {token}"}
    
    def create_mock_request_with_auth(
        self,
        user: User = None,
        token: str = None,
        **request_attrs
    ) -> MagicMock:
        """
        Create a mock FastAPI Request with authentication.
        
        Args:
            user: User object to associate with request
            token: JWT token (auto-generated if None and user provided)
            **request_attrs: Additional request attributes
        
        Returns:
            MagicMock configured as FastAPI Request
        """
        request_mock = MagicMock(spec=Request)
        
        # Configure basic request attributes
        request_mock.method = request_attrs.get("method", "GET")
        request_mock.url = request_attrs.get("url", "http://test/api/test")
        request_mock.headers = request_attrs.get("headers", {})
        request_mock.state = MagicMock()
        
        # Configure app state
        request_mock.app = MagicMock()
        request_mock.app.state = MagicMock()
        
        if user:
            if not token:
                token = self.generate_jwt_token(user)
            
            # Add authorization header
            request_mock.headers["authorization"] = f"Bearer {token}"
            
            # Set user in request state
            request_mock.state.user = user
            request_mock.state.user_id = user.id
        
        return request_mock
    
    def create_subscription_mock(
        self,
        user_id: str,
        tier: Union[str, SubscriptionTier] = SubscriptionTier.FREE,
        status: Union[str, SubscriptionStatus] = SubscriptionStatus.ACTIVE,
        **extra_fields
    ) -> MagicMock:
        """
        Create a mock subscription object.
        
        Args:
            user_id: User ID for subscription
            tier: Subscription tier
            status: Subscription status
            **extra_fields: Additional subscription fields
        
        Returns:
            MagicMock configured as Subscription
        """
        if isinstance(tier, str):
            tier = SubscriptionTier(tier)
        if isinstance(status, str):
            status = SubscriptionStatus(status)
        
        subscription_mock = MagicMock(spec=Subscription)
        subscription_mock.id = str(uuid.uuid4())
        subscription_mock.user_id = user_id
        subscription_mock.tier = tier
        subscription_mock.status = status
        subscription_mock.stripe_subscription_id = f"sub_{uuid.uuid4().hex[:10]}"
        subscription_mock.current_period_start = datetime.utcnow()
        subscription_mock.current_period_end = datetime.utcnow() + timedelta(days=30)
        subscription_mock.created_at = datetime.utcnow()
        subscription_mock.updated_at = datetime.utcnow()
        
        for key, value in extra_fields.items():
            setattr(subscription_mock, key, value)
        
        return subscription_mock
    
    def create_auth_service_mock(self, enabled: bool = True) -> AsyncMock:
        """
        Create AuthService mock.
        
        Args:
            enabled: Whether auth service is enabled
        
        Returns:
            AsyncMock configured as AuthService
        """
        auth_service_mock = AsyncMock()
        
        if enabled:
            # Mock successful authentication methods
            auth_service_mock.create_anonymous_session = AsyncMock(return_value=str(uuid.uuid4()))
            auth_service_mock.create_authenticated_session = AsyncMock(return_value=str(uuid.uuid4()))
            auth_service_mock.get_session_context = AsyncMock(return_value={
                "authenticated": True,
                "user_id": "test_user_123",
                "provider": "test",
                "session_id": "test_session_123"
            })
            auth_service_mock.update_session_activity = AsyncMock()
            auth_service_mock.invalidate_session = AsyncMock(return_value=True)
        else:
            # Mock disabled auth service
            auth_service_mock.create_anonymous_session = AsyncMock(return_value=None)
            auth_service_mock.create_authenticated_session = AsyncMock(return_value=None)
            auth_service_mock.get_session_context = AsyncMock(return_value={
                "authenticated": False,
                "user_id": None,
                "provider": None,
                "session_id": None
            })
        
        return auth_service_mock
    
    def patch_authentication_dependencies(
        self,
        user: User = None,
        auth_enabled: bool = True,
        subscription: MagicMock = None
    ) -> List[Any]:
        """
        Patch authentication dependencies for testing.
        
        Args:
            user: User to return from auth dependencies
            auth_enabled: Whether authentication is enabled
            subscription: Subscription to return for user
        
        Returns:
            List of patch objects
        """
        patches = []
        
        # Patch optional user dependency
        if user:
            patches.append(
                patch("app.core.auth_helpers.get_optional_user_with_logging", return_value=user)
            )
            patches.append(
                patch("app.core.auth_config.current_user_optional", return_value=user)
            )
        else:
            patches.append(
                patch("app.core.auth_helpers.get_optional_user_with_logging", return_value=None)
            )
            patches.append(
                patch("app.core.auth_config.current_user_optional", return_value=None)
            )
        
        # Patch auth service
        auth_service_mock = self.create_auth_service_mock(enabled=auth_enabled)
        patches.append(
            patch("app.core.dependencies.get_auth_service", return_value=auth_service_mock)
        )
        
        # Patch subscription if provided
        if subscription:
            patches.append(
                patch("app.core.dependencies.get_current_user_subscription", return_value=subscription)
            )
        
        return patches
    
    def create_admin_auth_context(self) -> Dict[str, Any]:
        """Create authentication context for admin user testing."""
        admin_user = self.create_admin_user()
        token = self.generate_jwt_token(admin_user)
        headers = self.create_auth_headers(token)
        request = self.create_mock_request_with_auth(admin_user, token)
        
        return {
            "user": admin_user,
            "token": token,
            "headers": headers,
            "request": request,
            "patches": self.patch_authentication_dependencies(admin_user)
        }
    
    def create_regular_user_auth_context(self) -> Dict[str, Any]:
        """Create authentication context for regular user testing."""
        user = self.create_test_user()
        token = self.generate_jwt_token(user)
        headers = self.create_auth_headers(token)
        request = self.create_mock_request_with_auth(user, token)
        
        return {
            "user": user,
            "token": token,
            "headers": headers,
            "request": request,
            "patches": self.patch_authentication_dependencies(user)
        }
    
    def create_premium_user_auth_context(self) -> Dict[str, Any]:
        """Create authentication context for premium user testing."""
        user = self.create_premium_user()
        subscription = self.create_subscription_mock(
            user.id,
            tier=SubscriptionTier.PREMIUM,
            status=SubscriptionStatus.ACTIVE
        )
        token = self.generate_jwt_token(user)
        headers = self.create_auth_headers(token)
        request = self.create_mock_request_with_auth(user, token)
        
        return {
            "user": user,
            "subscription": subscription,
            "token": token,
            "headers": headers,
            "request": request,
            "patches": self.patch_authentication_dependencies(user, subscription=subscription)
        }
    
    def create_unauthenticated_context(self) -> Dict[str, Any]:
        """Create context for unauthenticated user testing."""
        request = self.create_mock_request_with_auth()
        
        return {
            "user": None,
            "token": None,
            "headers": {},
            "request": request,
            "patches": self.patch_authentication_dependencies(user=None)
        }
    
    def create_invalid_auth_context(self) -> Dict[str, Any]:
        """Create context with invalid authentication for testing."""
        invalid_token = self.generate_invalid_token()
        headers = self.create_auth_headers(invalid_token)
        request = self.create_mock_request_with_auth(token=invalid_token)
        
        return {
            "user": None,
            "token": invalid_token,
            "headers": headers,
            "request": request,
            "patches": self.patch_authentication_dependencies(user=None)
        }
    
    def create_expired_auth_context(self) -> Dict[str, Any]:
        """Create context with expired authentication for testing."""
        user = self.create_test_user()
        expired_token = self.generate_expired_token(user)
        headers = self.create_auth_headers(expired_token)
        request = self.create_mock_request_with_auth(token=expired_token)
        
        return {
            "user": None,  # Expired token should not authenticate
            "token": expired_token,
            "headers": headers,
            "request": request,
            "patches": self.patch_authentication_dependencies(user=None)
        }
    
    def start_patches(self, patches: List[Any]) -> List[Any]:
        """Start all patches and track them for cleanup."""
        started_patches = []
        for patch_obj in patches:
            started_patch = patch_obj.__enter__()
            started_patches.append(patch_obj)
            self.active_patches.append(patch_obj)
        return started_patches
    
    def cleanup_patches(self):
        """Clean up all active patches."""
        for patch_obj in reversed(self.active_patches):
            try:
                patch_obj.__exit__(None, None, None)
            except Exception:
                pass
        self.active_patches.clear()
    
    def cleanup_all(self):
        """Clean up all resources."""
        self.cleanup_patches()
        self.mock_users.clear()


# Convenience functions for common auth testing patterns

def create_test_auth_context(
    user_type: str = "regular",
    auth_enabled: bool = True
) -> Dict[str, Any]:
    """
    Create authentication context for testing.
    
    Args:
        user_type: Type of user ("admin", "premium", "regular", "unauthenticated", "invalid", "expired")
        auth_enabled: Whether authentication is enabled
    
    Returns:
        Dictionary with auth context (user, token, headers, request, patches)
    """
    helper = AuthMockHelper()
    
    if user_type == "admin":
        return helper.create_admin_auth_context()
    elif user_type == "premium":
        return helper.create_premium_user_auth_context()
    elif user_type == "regular":
        return helper.create_regular_user_auth_context()
    elif user_type == "unauthenticated":
        return helper.create_unauthenticated_context()
    elif user_type == "invalid":
        return helper.create_invalid_auth_context()
    elif user_type == "expired":
        return helper.create_expired_auth_context()
    else:
        raise ValueError(f"Unknown user_type: {user_type}")


def patch_auth_for_endpoint_test(
    user: User = None,
    expected_status_codes: Dict[str, int] = None
):
    """
    Patch authentication for endpoint testing.
    
    Args:
        user: User to authenticate (None for unauthenticated)
        expected_status_codes: Expected HTTP status codes for different scenarios
    
    Returns:
        Patch context manager
    """
    helper = AuthMockHelper()
    patches = helper.patch_authentication_dependencies(user)
    
    class AuthPatchContext:
        def __enter__(self):
            helper.start_patches(patches)
            return helper
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            helper.cleanup_patches()
    
    return AuthPatchContext()


def create_mock_jwt_payload(
    user_id: str = "test_user_123",
    role: str = "user",
    **additional_claims
) -> Dict[str, Any]:
    """Create a mock JWT payload for testing."""
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "email": "test@example.com",
        "username": "testuser",
        "role": role,
        "is_active": True,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=24)).timestamp()),
        "iss": "ontologic-api-test",
        "aud": "ontologic-api",
        **additional_claims
    }
    return payload