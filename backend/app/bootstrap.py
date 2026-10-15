"""Process bootstrap shared by the API and the Arq worker.

Wires observability *before* features (Phase 0 principle), initialises the DB engine, and —
in the SQLite dev-fallback — creates the schema in-process so nothing external is required to
boot. On Postgres, schema + RLS come from Alembic migrations, not from here.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_tracing
from app.db.engine import init_engine

log = get_logger(__name__)


def init_runtime(settings: Settings) -> None:
    """Idempotent: logging + tracing + engine. Safe to call from API and worker startup.

    Each step guards its own re-entry (``configure_tracing`` once per process; ``init_engine``
    recreates only if disposed), so calling this again after a shutdown re-establishes the
    engine — which the test client relies on across cases.
    """
    configure_logging(level=settings.log_level, json=settings.log_json)
    configure_tracing(settings)
    init_engine(settings)


async def ensure_schema(settings: Settings) -> None:
    """Create tables for the SQLite dev-fallback. Postgres uses Alembic (see db/migrations)."""
    if not settings.is_sqlite:
        return
    import app.models  # noqa: F401  (register all models on the metadata)
    from app.db.base import Base
    from app.db.engine import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("schema.ensured", dialect="sqlite")
