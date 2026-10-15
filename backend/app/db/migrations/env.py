"""Alembic environment (async). Targets the Postgres path.

The DB URL comes from application settings. For the SQLite dev-fallback we don't run migrations
(schema is created in-process — see app/bootstrap.ensure_schema and ADR-0006); migrations are
the source of truth for Postgres, including RLS.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (register models on the metadata)
from app.config.settings import get_settings
from app.db.base import Base

target_metadata = Base.metadata
_settings = get_settings()
_url = _settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url, poolclass=None)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
