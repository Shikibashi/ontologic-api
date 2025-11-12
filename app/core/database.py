"""Unified database connection and session management."""

import os
from typing import AsyncGenerator
from sqlmodel import SQLModel, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.logger import log

# Database URL configuration
DATABASE_URL = os.environ.get("ONTOLOGIC_DB_URL", "sqlite:///./ontologic.db")

# Convert synchronous SQLite URL to async for SQLModel compatibility
if DATABASE_URL.startswith("sqlite:///"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
elif DATABASE_URL.startswith("postgresql://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
else:
    ASYNC_DATABASE_URL = DATABASE_URL

log.info(f"Database URL configured: {DATABASE_URL}")
log.info(f"Async Database URL: {ASYNC_DATABASE_URL}")

# Create async engine
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,  # Set to True for SQL logging during development
    future=True,
)

# Create async session maker
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_tables():
    """Initialize database tables. Unified method replacing init_db."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        log.info("Database tables initialized successfully")
    except Exception as e:
        log.error(f"Failed to initialize database: {e}")
        raise

async def init_db():
    """
    Backward compatibility shim for legacy startup and test code.
    
    DEPRECATED: This function exists solely to maintain compatibility with
    existing imports in app/main.py (line 24, line 63) and test patches in
    tests/conftest.py (line 261). New code should call init_tables() directly.
    
    This shim delegates to init_tables() without any additional logic.
    """
    await init_tables()

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session. Unified method replacing DatabaseManager."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
