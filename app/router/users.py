"""
User authentication router using FastAPI Users.

Provides endpoints for:
- User registration
- JWT login/logout
- User management (read, update, delete)
"""

from fastapi import APIRouter
from app.core.auth_config import auth_backend, fastapi_users
from app.core.user_models import UserRead, UserCreate, UserUpdate


# Create router
router = APIRouter()

# Include FastAPI Users authentication routes
# POST /auth/register - Register new user
# POST /auth/jwt/login - Login and get JWT token
# POST /auth/jwt/logout - Logout (revoke token)
router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt",
    tags=["auth"],
)

# Include user management routes
# GET /users/me - Get current user
# PATCH /users/me - Update current user
# DELETE /users/me - Delete current user (requires password confirmation)
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)

# Include registration route
# POST /auth/register
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)

# Include password reset routes (optional, can be removed if not needed)
# POST /auth/forgot-password
# POST /auth/reset-password
router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)

# Include email verification routes (optional, can be removed if not needed)
# POST /auth/request-verify-token
# POST /auth/verify
router.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
