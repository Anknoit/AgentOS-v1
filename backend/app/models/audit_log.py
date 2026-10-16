from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class AuditLog(Base, TenantScopedMixin):
    """Append-only, tenant-scoped audit trail of **control-plane** mutations (Phase 6, SOC 2).

    Distinct from ``action_log`` (what an *agent run* did): this records what a *principal* did to
    the account — created an agent, stored a credential, minted an API key, changed a role, issued a
    top-up, rotated keys, published to the marketplace. Every row names the actor, the action, and
    the resource, with the request ``trace_id`` so it ties back to logs/spans. Rows are never
    updated or deleted (retention purges are the only exception, and the money ledger is never
    touched), and the whole trail is exportable for a security review.
    """

    __tablename__ = "audit_log"

    # Who acted: the user/key id (or "system"), and how they authenticated.
    actor_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="system")
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # What happened: a dotted action (e.g. "agent.create", "apikey.revoke", "keys.rotate") and the
    # resource it targeted.
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Non-secret context (never credentials/secrets) and the request trace id.
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
