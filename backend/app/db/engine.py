"""Async engine + session factory.

The engine URL decides the profile (ADR-0006): ``postgresql+asyncpg://`` for the real path,
``sqlite+aiosqlite://`` for the zero-dependency dev fallback.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config.settings import Settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None


def _connect_args(settings: Settings) -> dict:
    if settings.is_sqlite:
        # Allow use across the event loop's threads; fine for the dev fallback.
        return {"check_same_thread": False}
    return {}


def init_engine(settings: Settings) -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine
    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=not settings.is_sqlite,
        connect_args=_connect_args(settings),
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("engine not initialised — call init_engine() first")
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    if _sessionmaker is None:
        raise RuntimeError("engine not initialised — call init_engine() first")
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
