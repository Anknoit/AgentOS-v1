from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class AgentVersion(Base, TenantScopedMixin):
    """Immutable, versioned agent configuration.

    A version is written once and never updated — a run pins the exact ``agent_version`` it
    executed, so behaviour is reproducible and a bad change is a one-line rollback (point the
    agent's ``current_version_id`` back). ``version`` is monotonic per agent.

    The config fields are deliberately explicit (model, prompt, tools, guardrails, knowledge,
    connector bindings) rather than one opaque blob, so they are queryable and diffable. JSON
    columns are portable across the Postgres and SQLite profiles (ADR-0006).
    """

    __tablename__ = "agent_version"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "version", name="uq_agent_version"),
    )

    agent_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    model: Mapped[str] = mapped_column(String(128), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Tool names the runtime may call this version (Phase 1: built-in tools; Phase 2: connectors).
    tools: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Guardrails: max_steps, max_tokens, allowed topics, etc. Enforced by the kernel.
    guardrails: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Knowledge refs (doc ids / collection names); retrieval is a built-in tool in Phase 1.
    knowledge: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Connector bindings (scoped capabilities) — wired in Phase 2; stored now so config is stable.
    connector_bindings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
