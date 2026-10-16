from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class Tenant(Base, IdMixin, TimestampMixin):
    """Organization account — the root of isolation and billing."""

    __tablename__ = "tenant"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Data-residency label pinned at creation (Phase 6). Immutable once set — moving a tenant's data
    # across regions is an explicit migration, not a field edit. Surfaced in the compliance report.
    region: Mapped[str] = mapped_column(String(32), default="global", nullable=False)
