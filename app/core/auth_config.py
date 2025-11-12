"""
Authentication configuration using FastAPI Users.

Provides JWT authentication backend and user management setup.
"""

import os
from typing import Optional
from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, IntegerIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.user_models import User
from app.core.logger import log
from app.config.settings import get_settings


def get_jwt_secret() -> str:
    """Get JWT secret from settings."""
    settings = get_settings()
    secret = settings.jwt_secret.get_secret_value()
    if secret == "CHANGE_THIS_IN_PRODUCTION":
        log.warning(
            "Using default JWT secret! Set APP_JWT_SECRET environment variable in production."
        )
    return secret


# Get secret at module load time
SECRET = get_jwt_secret()


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    """
    User manager for handling user operations.

    Handles user registration, verification, and password reset logic.
    """

    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Optional = None):
        """Hook called after successful user registration."""
        log.info(f"User {user.id} ({user.email}) has registered.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional = None
    ):
        """Hook called after forgot password request."""
        log.info(f"User {user.id} ({user.email}) has requested password reset.")

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional = None
    ):
        """Hook called after verification email request."""
        log.info(f"Verification requested for user {user.id} ({user.email}).")

    async def get(self, user_id):  # type: ignore[override]
        """Fetch a user by ID with additional debug logging for JWT validation."""
        log.debug("UserManager.get invoked for user_id=%s", user_id)
        user = await super().get(user_id)
        if user:
            log.debug(
                "UserManager.get resolved user_id=%s email=%s is_active=%s",
                user_id,
                user.email,
                getattr(user, "is_active", "unknown"),
            )
        else:
            log.warning(
                "UserManager.get could not find user_id=%s during authentication lookup",
                user_id,
            )
        return user


async def get_user_db():
    """
    Get user database session for FastAPI Users.

    Integrates with the app's database session management from database.py.
    Uses get_session() to obtain async database sessions.
    """
    # Import here to avoid circular dependencies at module load time
    from app.core.database import get_session

    # Get session from database dependency
    async for db_session in get_session():
        log.debug("Creating SQLAlchemyUserDatabase session for authentication flow")
        try:
            yield SQLAlchemyUserDatabase(db_session, User)
        finally:
            log.debug("Releasing SQLAlchemyUserDatabase session for authentication flow")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    """Get user manager instance."""
    yield UserManager(user_db)


def get_jwt_strategy() -> JWTStrategy:
    """Get JWT authentication strategy used for issuing and validating tokens."""
    settings = get_settings()
    strategy = JWTStrategy(
        secret=SECRET,
        lifetime_seconds=settings.jwt_lifetime_seconds,
    )
    log.debug(
        "JWT strategy instantiated with lifetime_seconds=%s", settings.jwt_lifetime_seconds
    )
    return strategy


# Bearer token transport (Authorization: Bearer <token>)
bearer_transport = BearerTransport(tokenUrl="/auth/jwt/login")

# JWT authentication backend
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

# FastAPI Users instance
fastapi_users = FastAPIUsers[User, int](
    get_user_manager,
    [auth_backend],
)

# Current user dependencies
current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
current_user_optional = fastapi_users.current_user(optional=True)
