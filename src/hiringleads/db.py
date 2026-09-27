"""Async PostgreSQL engine and transaction helpers."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = settings()
        _engine = create_async_engine(
            s.database_url,
            pool_pre_ping=True,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout,
            echo=False,
            connect_args={"server_settings": {"application_name": "hiringleads"}}
            if s.database_url.startswith("postgresql+asyncpg")
            else {},
        )
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(
            engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _factory


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


async def ping() -> None:
    async with engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def create_all() -> None:
    """Development-only schema bootstrap. Production uses Alembic."""
    from .models import Base

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _factory = None
