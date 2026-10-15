"""Structured logging (structlog).

Every log line carries the current ``trace_id`` and ``tenant_id`` from the request context, so
a single trace is greppable across API and worker. Human-readable in dev, JSON in prod.
"""

from __future__ import annotations

import logging

import structlog

from app.core.context import get_tenant_id, get_trace_id


def _inject_context(_logger, _method, event_dict):
    tid = get_trace_id()
    if tid:
        event_dict.setdefault("trace_id", tid)
    tenant = get_tenant_id()
    if tenant:
        event_dict.setdefault("tenant_id", tenant)
    return event_dict


def configure_logging(*, level: str = "INFO", json: bool = False) -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _inject_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
