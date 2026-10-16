from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class MarketplaceListing(Base, IdMixin, TimestampMixin):
    """A shareable agent template or connector config, published for other tenants to install.

    **This is the one table deliberately outside the tenant-isolation boundary** (no RLS): the
    marketplace is a public catalogue (the network-effect lever — Phase 6, build task 4). It still
    records ``publisher_tenant_id`` for attribution, but reads are cross-tenant by design, so all
    access goes through a ``system_session``, never ``tenant_session``.

    ``config`` is the installable payload — an ``AgentVersionConfig`` for ``agent_template`` or a
    connector's non-secret ``provider_meta`` for ``connector``. **Secrets are never published**: an
    installer brings their own credentials. Installing copies ``config`` into the caller's tenant.
    """

    __tablename__ = "marketplace_listing"

    publisher_tenant_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # "agent_template" | "connector"
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    installs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
