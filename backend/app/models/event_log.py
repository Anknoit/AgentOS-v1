"""The durable event log — the replayable, offset-ordered usage stream (Phase 5).

Phase 3 made metering event-driven (``usage.captured`` on the bus); Phase 5 makes that stream
**durable and replayable** — the dev-fallback analogue of a Kafka topic. Every published event is
appended here, in order, under a monotonically increasing ``offset``. A consumer tracks how far it
has processed in ``consumer_offset`` and can be rewound to re-process a range; because the metering
pipeline is idempotent (ledger unique on ``(tenant_id, usage_event_id)``), a replay produces no new
ledger entries and no balance change — the exactly-once guarantee under replay.

Unlike the rest of the model this table does **not** use the uuid ``IdMixin``: its primary key is
the stream ``offset`` itself, a DB-native autoincrement that is monotonic on both SQLite (INTEGER
PRIMARY KEY) and Postgres (identity), so offsets are orderable and gap-resumable. ``tenant_id`` is
still the isolation boundary (RLS on Postgres); a consumer cursor is kept per tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# SQLite only autoincrements an INTEGER PRIMARY KEY (its rowid alias); a BIGINT PK does not. The
# variant keeps a true BIGSERIAL on Postgres and a working autoincrement on the SQLite dev-fallback.
_Offset = BigInteger().with_variant(Integer, "sqlite")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EventLog(Base):
    """One appended event in the durable stream. Append-only; never updated or deleted."""

    __tablename__ = "event_log"

    # The stream offset: DB-native monotonic integer PK (Kafka-partition-offset analogue).
    offset: Mapped[int] = mapped_column(_Offset, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )
