"""Declarative base and common column mixins.

Columns are kept dialect-portable (ADR-0006): the same models run on Postgres and the SQLite
dev-fallback. Postgres-only DDL (RLS, partitioning) lives in migrations, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now,
        onupdate=_now,
        server_default=func.now(),
        nullable=False,
    )


class TenantScopedMixin(IdMixin, TimestampMixin):
    """Every tenant-owned row carries ``tenant_id`` — the isolation boundary (RLS on Postgres)."""

    tenant_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
