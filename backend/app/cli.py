"""CLI entrypoint (``agentos``), also how Electron launches the sidecar.

``agentos serve`` runs uvicorn with the configured host/port; ``agentos worker`` runs the Arq
worker. Electron spawns ``python -m app.cli serve --port <p>`` (or the PyInstaller binary).
"""

from __future__ import annotations

import argparse
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
