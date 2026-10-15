"""Async engine + session factory.

The engine URL decides the profile (ADR-0006): ``postgresql+asyncpg://`` for the real path,
``sqlite+aiosqlite://`` for the zero-dependency dev fallback.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config.settings import Settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker | None = None
# HA/DR (Phase 5): an optional read-replica engine. Reads that tolerate replication lag can be
# routed here to take load off the primary; it falls back to the primary when unconfigured.
_read_engine: AsyncEngine | None = None
_read_sessionmaker: async_sessionmaker | None = None


def _connect_args(settings: Settings) -> dict:
    if settings.is_sqlite:
        # Allow use across the event loop's threads; fine for the dev fallback.
        return {"check_same_thread": False}
    return {}


def init_engine(settings: Settings) -> AsyncEngine:
    global _engine, _sessionmaker, _read_engine, _read_sessionmaker
    if _engine is not None:
        return _engine
    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=not settings.is_sqlite,
        connect_args=_connect_args(settings),
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)

    if settings.read_replica_url:
        _read_engine = create_async_engine(
            settings.read_replica_url,
            echo=False,
            pool_pre_ping=True,
            connect_args=_connect_args(settings),
        )
        _read_sessionmaker = async_sessionmaker(
            _read_engine, expire_on_commit=False, autoflush=False
        )
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("engine not initialised — call init_engine() first")
    return _engine


def get_sessionmaker() -> async_sessionmaker:
    if _sessionmaker is None:
        raise RuntimeError("engine not initialised — call init_engine() first")
    return _sessionmaker


def get_read_sessionmaker() -> async_sessionmaker:
    """The replica session factory, or the primary's when no replica is configured."""
    if _read_sessionmaker is not None:
        return _read_sessionmaker
    return get_sessionmaker()


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _read_engine, _read_sessionmaker
    if _engine is not None:
        await _engine.dispose()
    if _read_engine is not None:
        await _read_engine.dispose()
    _engine = None
    _sessionmaker = None
    _read_engine = None
    _read_sessionmaker = None
