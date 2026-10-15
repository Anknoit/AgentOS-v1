from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Credential(Base, TenantScopedMixin):
    """A connector credential, stored **encrypted per tenant** (ADR-0008).

    ``ciphertext`` is the Fernet token of the secret (OAuth access/refresh token or API key),
    encrypted with a key derived from the deployment master secret and this row's ``tenant_id``
    — so the plaintext is never at rest and a leaked row is useless to another tenant.

    ``provider_meta`` holds **non-secret** context the connector needs (workspace id, base URL,
    MCP server URL), and ``scopes`` records what the credential itself was granted by the provider
    (distinct from what an ``agent_version`` grants an agent). ``(tenant_id, connector_key, name)``
    is unique so a tenant can keep several named credentials per connector (e.g. two Slack
    workspaces).
    """

    __tablename__ = "credential"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_key", "name", name="uq_credential_tenant_key"),
    )

    connector_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False)  # oauth | api_key | none
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    provider_meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
