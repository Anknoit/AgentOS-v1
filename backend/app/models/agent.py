from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Agent(Base, TenantScopedMixin):
    """A logical agent — an "employee" in the fleet.

    The ``agent`` row is the stable control-plane identity; its *behaviour* lives in immutable
    ``agent_version`` rows (config is data, and versioned — a core principle).
    ``current_version_id`` points at the version new runs pin by default; editing an agent mints
    a new version and advances this pointer, so changes are diffable and rollback-able.

    ``current_version_id`` is a plain string ref (not a DB FK) to stay consistent with the rest
    of the schema, which avoids hard FKs so RLS and per-table lifecycle stay simple.
    """

    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_agent_tenant_slug"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    # The template this agent was created from (e.g. "support_desk"); free-form role label too.
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # draft | active | paused | archived
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
