"""Backup & restore — the HA/DR foundation (Phase 5, build task 6).

A disaster-recovery story is only real if the restore is *tested*, so backup/restore is a first-
class, scripted operation, not a wiki page. Two dialects, one contract:

* **SQLite** (dev-fallback): a consistent snapshot via SQLite's online backup API (copies a live DB
  without corrupting in-flight writes), and restore by atomically swapping the file in.
* **Postgres** (prod): ``pg_dump`` to a custom-format archive and ``pg_restore`` back — shelled out
  so the heavy lifting stays with the database's own battle-tested tooling.

The ``agentos backup`` / ``agentos restore`` CLI wrap these. RPO is bounded by backup cadence (plus
WAL/PITR on managed Postgres); RTO by restore time — both documented in docs/runbook-dr.md. The
test suite exercises the SQLite path end to end (populate → backup → mutate → restore → verify the
ledger re-derives), which is the "tested restore" the exit criteria call for.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _dialect(settings: Settings) -> str:
    return "sqlite" if settings.is_sqlite else "postgres"


def _sqlite_path(url: str) -> Path:
    # sqlite+aiosqlite:///./agentos.db  ->  ./agentos.db
    tail = url.split(":///", 1)[1] if ":///" in url else url.split("://", 1)[1]
    return Path(tail)


def _default_dest(settings: Settings) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "sqlite" if settings.is_sqlite else "dump"
    return Path(f"agentos-backup-{stamp}.{suffix}")


def backup_db(dest: str | Path | None = None, *, settings: Settings | None = None) -> Path:
    """Write a consistent snapshot of the database to ``dest``; returns the path written."""
    settings = settings or get_settings()
    dest = Path(dest) if dest is not None else _default_dest(settings)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if settings.is_sqlite:
        src = _sqlite_path(settings.database_url)
        # Online backup API: a consistent copy even with concurrent writers.
        source = sqlite3.connect(str(src))
        try:
            target = sqlite3.connect(str(dest))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
    else:
        parsed = urlparse(settings.database_url.replace("+asyncpg", ""))
        subprocess.run(
            ["pg_dump", "--format=custom", f"--file={dest}", _pg_conn(parsed)],
            check=True,
        )
    log.info("backup.written", dest=str(dest), dialect=_dialect(settings))
    return dest


def restore_db(src: str | Path, *, settings: Settings | None = None) -> None:
    """Restore the database from a snapshot at ``src``.

    Destructive: replaces current data. Callers must quiesce writers and dispose the engine first
    (the CLI does), then re-init afterwards. On SQLite this swaps the file atomically.
    """
    settings = settings or get_settings()
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"backup not found: {src}")

    if settings.is_sqlite:
        dest = _sqlite_path(settings.database_url)
        tmp = dest.with_suffix(dest.suffix + ".restoring")
        shutil.copyfile(src, tmp)
        tmp.replace(dest)  # atomic swap on the same filesystem
    else:
        parsed = urlparse(settings.database_url.replace("+asyncpg", ""))
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner",
             "--dbname", _pg_conn(parsed), str(src)],
            check=True,
        )
    log.info("restore.done", src=str(src), dialect=_dialect(settings))


def _pg_conn(parsed) -> str:
    """Rebuild a libpq connection string from a parsed SQLAlchemy URL."""
    user = parsed.username or "postgres"
    pw = f":{parsed.password}" if parsed.password else ""
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    db = (parsed.path or "/postgres").lstrip("/")
    return f"postgresql://{user}{pw}@{host}{port}/{db}"
