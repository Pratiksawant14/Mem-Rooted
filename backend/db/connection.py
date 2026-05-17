"""
Mem-Rooted — Async PostgreSQL Connection Pool
Uses asyncpg via SQLAlchemy async engine with pgvector extension.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import asyncpg
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    """Database configuration loaded from environment variables."""

    DATABASE_URL: str = "postgresql+asyncpg://memrooted:memrooted_dev@localhost:5432/memrooted"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = DatabaseSettings()

# ── Async Engine ──────────────────────────────────────────────────────────────

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=False,
    connect_args={
        "server_settings": {"jit": "off"}
    }
)

# ── Session Factory ───────────────────────────────────────────────────────────

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# ── Dependency Injection ─────────────────────────────────────────────────────

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session with automatic commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session per request."""
    async with get_session() as session:
        yield session


# ── Initialization ────────────────────────────────────────────────────────────

async def init_pgvector_extension(engine: AsyncEngine) -> None:
    """Ensure the pgvector extension is enabled in PostgreSQL."""
    async with engine.begin() as conn:
        await conn.execute(
            # Raw SQL — SQLAlchemy doesn't manage extensions
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector;")
        )


async def init_db() -> None:
    """Initialize database: enable pgvector, create tables."""
    await init_pgvector_extension(engine)

    # Import models so metadata is populated before create_all
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the connection pool on shutdown."""
    await engine.dispose()
