"""Инициализация async SQLAlchemy для PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bootstrap import load_bootstrap

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def normalize_database_url(url: str) -> str:
    """Приводит PostgreSQL URL к asyncpg-драйверу SQLAlchemy."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


async def init_engine(database_url: str | None = None) -> AsyncEngine:
    """Создаёт или возвращает глобальный SQLAlchemy engine."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    if database_url is None:
        cfg = load_bootstrap()
        if cfg is None:
            raise RuntimeError("Application is not configured")
        database_url = cfg.database_url

    _engine = create_async_engine(
        normalize_database_url(database_url),
        pool_pre_ping=True,
        future=True,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def close_engine() -> None:
    """Закрывает соединения с Postgres."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: выдаёт короткую транзакционную сессию."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Application setup is not completed")
    async with _session_factory() as session:
        yield session


@asynccontextmanager
async def session_context() -> AsyncIterator[AsyncSession]:
    """Контекстная async-сессия для фоновых задач."""
    if _session_factory is None:
        await init_engine()
    assert _session_factory is not None
    async with _session_factory() as session:
        yield session
