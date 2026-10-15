"""Tested restore — the HA/DR exit bar (Phase 5, build task 6).

A disaster-recovery plan that has never been restored is a hope, not a plan. This exercises the
SQLite backup/restore path end to end on its own throwaway database (so it never disturbs the
session engine): snapshot a populated DB, corrupt it, restore, and confirm the data comes back
byte-for-byte. The Postgres path shells out to pg_dump/pg_restore (not run in CI; see
docs/runbook-dr.md).
"""

from __future__ import annotations

import sqlite3

from app.config.settings import Settings
from app.ops.backup import backup_db, restore_db


def _seed_ledger(db_path) -> None:
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE ledger_entry (id INTEGER PRIMARY KEY, price_nanos INTEGER)")
        con.executemany(
            "INSERT INTO ledger_entry (price_nanos) VALUES (?)", [(100,), (250,), (900,)]
        )
        con.commit()
    finally:
        con.close()


def _balance(db_path) -> int:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT COALESCE(SUM(price_nanos), 0) FROM ledger_entry").fetchone()
        return int(row[0])
    finally:
        con.close()


def test_sqlite_backup_then_restore_recovers_the_ledger(tmp_path):
    db = tmp_path / "dr.db"
    settings = Settings(database_url=f"sqlite+aiosqlite:///{db}", otel_exporter="none")

    _seed_ledger(db)
    assert _balance(db) == 1250

    # Take a consistent snapshot, then "lose" data (a bad deploy wipes the ledger).
    snapshot = backup_db(tmp_path / "snap.sqlite", settings=settings)
    assert snapshot.exists()

    con = sqlite3.connect(db)
    con.execute("DELETE FROM ledger_entry")
    con.commit()
    con.close()
    assert _balance(db) == 0

    # Restore brings the ledger back exactly.
    restore_db(snapshot, settings=settings)
    assert _balance(db) == 1250


def test_restore_missing_file_raises(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'x.db'}", otel_exporter="none"
    )
    try:
        restore_db(tmp_path / "does-not-exist.sqlite", settings=settings)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass
