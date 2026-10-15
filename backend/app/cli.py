"""CLI entrypoint (``agentos``), also how Electron launches the sidecar.

``agentos serve`` runs uvicorn with the configured host/port; ``agentos worker`` runs the Arq
worker. Electron spawns ``python -m app.cli serve --port <p>`` (or the PyInstaller binary). Phase 5
adds the reliability/DR operator commands: ``replay`` (re-feed the usage stream through the
idempotent pipeline — the exactly-once / recovery tool), ``backup``, and ``restore``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config.settings import get_settings


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0


def _worker(_args: argparse.Namespace) -> int:
    from arq import run_worker

    from app.runtime.queue import WorkerSettings

    run_worker(WorkerSettings)  # type: ignore[arg-type]
    return 0


def _replay(args: argparse.Namespace) -> int:
    from app.bootstrap import ensure_schema, init_runtime
    from app.metering.stream import replay_usage

    settings = get_settings()

    async def _run() -> int:
        init_runtime(settings)
        await ensure_schema(settings)
        r = await replay_usage(args.tenant, from_offset=args.from_offset, commit=not args.dry_run)
        print(
            f"replayed={r.replayed} repaired={r.repaired} "
            f"new_ledger_entries={r.new_ledger_entries} "
            f"balance_delta={r.balance_delta} exactly_once={r.exactly_once}"
        )
        return 0 if r.exactly_once else 1

    return asyncio.run(_run())


def _backup(args: argparse.Namespace) -> int:
    from app.ops.backup import backup_db

    dest = backup_db(args.dest)
    print(f"backup written: {dest}")
    return 0


def _restore(args: argparse.Namespace) -> int:
    from app.bootstrap import init_runtime
    from app.db.engine import dispose_engine
    from app.ops.backup import restore_db

    settings = get_settings()

    async def _run() -> int:
        init_runtime(settings)
        await dispose_engine()  # quiesce: no engine holds the DB file during the swap
        restore_db(args.src)
        print(f"restored from: {args.src}")
        return 0

    return asyncio.run(_run())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentos", description="AgentOS backend")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the HTTP/WebSocket API (uvicorn)")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_serve)

    p_worker = sub.add_parser("worker", help="Run the Arq worker")
    p_worker.set_defaults(func=_worker)

    p_replay = sub.add_parser("replay", help="Replay a tenant's usage stream (exactly-once check)")
    p_replay.add_argument("tenant", help="tenant id to replay")
    p_replay.add_argument("--from-offset", type=int, default=None, dest="from_offset")
    p_replay.add_argument("--dry-run", action="store_true", help="do not advance the offset")
    p_replay.set_defaults(func=_replay)

    p_backup = sub.add_parser("backup", help="Write a consistent DB snapshot")
    p_backup.add_argument("--dest", default=None, help="output path (default: timestamped file)")
    p_backup.set_defaults(func=_backup)

    p_restore = sub.add_parser("restore", help="Restore the DB from a snapshot (destructive)")
    p_restore.add_argument("src", help="backup file to restore from")
    p_restore.set_defaults(func=_restore)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
