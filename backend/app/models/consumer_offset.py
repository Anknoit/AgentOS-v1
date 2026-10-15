"""A stream consumer's committed position (Phase 5).

One row per ``(tenant_id, consumer)`` records how far a named consumer has processed the durable
:class:`~app.models.event_log.EventLog`. Committing the offset *after* a batch is handled is the
idempotent checkpoint: a crash between handling and commit replays the last batch, which the
idempotent pipeline absorbs without double-counting. Lag — how far a consumer trails the head — is
``head_offset − committed_offset`` and is what the ops endpoint reports as ingestion health.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class ConsumerOffset(Base, TenantScopedMixin):
    __tablename__ = "consumer_offset"
    __table_args__ = (
        UniqueConstraint("tenant_id", "consumer", name="uq_consumer_offset"),
    )

    consumer: Mapped[str] = mapped_column(String(64), nullable=False)
    committed_offset: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
