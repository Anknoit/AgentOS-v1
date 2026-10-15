from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScopedMixin


class Budget(Base, TenantScopedMixin):
    """A spend cap, checked **before** each billable action — online credit control (Phase 3).

    ``scope`` is ``tenant`` (all agents) or ``agent`` (``scope_id`` = the agent id); ``period`` is
    ``total``, ``daily``, or ``monthly`` (the window spend is summed over). ``enforcement`` is
    ``soft`` (alert only, work continues) or ``hard`` (stop the agent at the limit). When period
    spend reaches ``limit_nanos`` a hard budget denies further billable actions, so an agent stops
    *at* its cap rather than overrunning it; a soft budget raises an alert and lets work proceed.
    """

    __tablename__ = "budget"

    name: Mapped[str] = mapped_column(String(64), nullable=False, default="budget")
    # scope: tenant (all agents) | agent (scope_id)
    scope: Mapped[str] = mapped_column(String(16), default="tenant", nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    # period the spend is summed over: total | daily | monthly
    period: Mapped[str] = mapped_column(String(16), default="total", nullable=False)
    limit_nanos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # enforcement: soft (alert) | hard (stop at the limit)
    enforcement: Mapped[str] = mapped_column(String(8), default="hard", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
