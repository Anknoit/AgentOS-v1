"""Checkpointer seam (ADR-0007).

The agent kernel is a LangGraph graph; its checkpointer persists graph state after every step so
a run can be **resumed across a worker restart** (``thread_id = run_id``). The checkpoint store is
kept *separate from the application database* so LangGraph's writer never contends for the app's
SQLite file lock:

* SQLite dev-fallback → ``AsyncSqliteSaver`` on a sibling file (``<db>.ckpt``);
* in-memory SQLite → ``MemorySaver`` (resume within the process only — there is no file to survive);
* Postgres full stack → ``AsyncPostgresSaver`` (lazy import; ``langgraph-checkpoint-postgres``).

Exactly-once accounting does **not** depend on where the checkpoint lives: usage events use
deterministic idempotency keys, so a step that replays after a resume dedupes regardless.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.engine import make_url

from app.config.settings import Settings


def _sqlite_path(database_url: str) -> str | None:
    """Return the filesystem path for a SQLite URL, or ``None`` for in-memory."""
    db = make_url(database_url).database
    if not db or db == ":memory:":
        return None
    return db


@asynccontextmanager
async def checkpointer_cm(settings: Settings) -> AsyncIterator[object]:
    """Yield a LangGraph checkpointer appropriate for the active profile."""
    if settings.is_sqlite:
        path = _sqlite_path(settings.database_url)
        if path is None:
            from langgraph.checkpoint.memory import MemorySaver

            yield MemorySaver()
            return
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(f"{path}.ckpt") as saver:
            yield saver
        return

    # Postgres full stack: the durable checkpointer for the cloud/worker deployment.
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore

    # LangGraph's Postgres saver speaks psycopg DSN (postgresql://...), not the asyncpg driver URL.
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()
        yield saver
