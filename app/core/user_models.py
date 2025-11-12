"""
User authentication models using FastAPI Users.

Provides user database models, schemas, and authentication configuration
for JWT-based authentication.
"""

import warnings
from typing import Optional
from fastapi_users import schemas
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime
from sqlalchemy.sql import func
from datetime import datetime, timezone
from app.core.db_models import SubscriptionTier, SubscriptionStatus

# Suppress SQLModel/Pydantic warnings about field shadowing
# These warnings occur due to FastAPI Users' base class structure
warnings.filterwarnings("ignore", category=UserWarning, module="sqlmodel")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic._internal._fields")


class User(SQLModel, table=True):
    """
    User model for authentication.

    Pure SQLModel implementation that implements the same interface as
    SQLAlchemyBaseUserTable but without inheritance conflicts.
    
    This avoids the shadowing warnings that occur when inheriting from
    both SQLAlchemyBaseUserTable and SQLModel.
    """

    __tablename__ = "users"
    
    # Core authentication fields (same as SQLAlchemyBaseUserTable)
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=320)
    hashed_password: str = Field(max_length=1024)
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    is_verified: bool = Field(default=False)

    # Additional application-specific fields
    username: Optional[str] = Field(default=None, unique=True, index=True, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column=Column(DateTime(timezone=True), onupdate=func.now()))
    
    # Payment-related fields
    stripe_customer_id: Optional[str] = Field(default=None, unique=True, index=True)
    subscription_tier: SubscriptionTier = Field(default=SubscriptionTier.FREE)
    subscription_status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)


# Pydantic schemas for API requests/responses
class UserRead(schemas.BaseUser[int]):
    """Schema for reading user data (response)."""

    username: Optional[str]
    created_at: datetime
    subscription_tier: SubscriptionTier
    subscription_status: SubscriptionStatus


class UserCreate(schemas.BaseUserCreate):
    """Schema for creating a user (request)."""

    username: Optional[str]


class UserUpdate(schemas.BaseUserUpdate):
    """Schema for updating a user (request)."""

    username: Optional[str]
