"""Session helpers that carry the tenant boundary into the data layer.

* ``tenant_session(tenant_id)`` — the normal path. On Postgres it sets the transaction-local
  GUC ``app.current_tenant`` so row-level security policies apply (the isolation boundary lives
  in the database). On the SQLite dev-fallback it stashes the tenant on ``session.info`` so the
  repository layer can mirror the same scoping (RLS is only *enforced* on Postgres — ADR-0006).
* ``system_session()`` — no tenant; used only for the auth lookup (resolve an API key before we
  know the tenant) and startup seeding. It touches identity tables only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.db.engine import get_read_sessionmaker, get_sessionmaker


@asynccontextmanager
async def tenant_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    sm = get_sessionmaker()
    async with sm() as session:
        session.info["tenant_id"] = tenant_id
        async with session.begin():
            if not settings.is_sqlite:
                # Transaction-local: reset automatically on commit/rollback, so it never
                # leaks to the next pool checkout.
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, true)"),
                    {"tid": tenant_id},
                )
            yield session


@asynccontextmanager
async def read_session(tenant_id: str) -> AsyncIterator[AsyncSession]:
    """A tenant-scoped **read** session, routed to the replica when one is configured (Phase 5).

    Same RLS/tenant scoping as :func:`tenant_session` but on the read-replica engine (falling back
    to the primary when unset), for reads that tolerate replication lag — reporting/ops queries, not
    anything that then writes. Still opens a transaction so the RLS GUC applies on Postgres.
    """
    settings = get_settings()
    sm = get_read_sessionmaker()
    async with sm() as session:
        session.info["tenant_id"] = tenant_id
        async with session.begin():
            if not settings.is_sqlite:
                await session.execute(
                    text("SELECT set_config('app.current_tenant', :tid, true)"),
                    {"tid": tenant_id},
                )
            yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as session:
        async with session.begin():
            yield session
