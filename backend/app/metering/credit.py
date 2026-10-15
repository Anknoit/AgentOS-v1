"""Online credit control — check budgets and balance *before* each billable action (Phase 3).

This is the "authorize" half of the telecom online-charging pattern: the runtime calls
:meth:`CreditController.authorize` ahead of every model, tool, and connector call; the "charge"
half is the ledger debit that :mod:`app.metering.pipeline` writes afterwards. A hard budget that
has reached its limit raises :class:`BudgetExceededError`, which stops the agent *at* the cap; a
soft budget raises an alert and lets the work proceed. Prepaid-balance enforcement (Phase 4) is
wired here too but off by default while keys are BYO.

A controller is constructed per run with the run's tenant/agent and carries no ambient authority.
Spend is read from the append-only ledger (the source of truth), scoped to the budget's window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.errors import BudgetExceededError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.metering.anomaly import raise_alert
from app.metering.money import format_usd
from app.models.budget import Budget
from app.models.ledger_entry import LedgerEntry
from app.models.wallet import Wallet

log = get_logger(__name__)


def _period_start(period: str, now: datetime) -> datetime | None:
    if period == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return None  # "total": all time


@dataclass
class CreditController:
    tenant_id: str
    agent_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    # seq -> reserved estimate (Phase 4 hold); released when the real debit lands or at run end.
    holds: dict[int, int] = field(default_factory=dict)

    async def authorize(
        self, *, kind: str, estimate_nanos: int = 0, seq: int | None = None
    ) -> None:
        """Permit or refuse the next billable action. Raises ``BudgetExceededError`` on a hard cap.

        ``kind`` is the action type (``model_call`` / ``tool_call`` / ``connector_call``) and
        ``estimate_nanos`` an upper-bound guess of its price. Hard budgets stop at the limit on
        realized spend, so an agent runs up to its cap then halts. When the wallet enforces a
        prepaid balance (Phase 4), the check is against *available* funds (balance − reserved) and
        the estimate is **reserved** on success — so a burst of concurrent actions can't each pass a
        check that only one of them fits; the real debit later releases the hold.

        Soft alerts are written in the read transaction (which commits normally); the stop decision
        is made there but the denial is *raised after* the transaction closes, so the
        ``budget_hard`` alert is written in its own committed transaction and never rolled back by
        the raise.
        """
        now = datetime.now(timezone.utc)
        deny: dict | None = None

        async with tenant_session(self.tenant_id) as session:
            budgets = (
                await session.execute(
                    select(Budget).where(
                        Budget.tenant_id == self.tenant_id, Budget.is_active.is_(True)
                    )
                )
            ).scalars().all()

            for b in budgets:
                if b.scope == "agent" and b.scope_id != self.agent_id:
                    continue
                spend = await self._period_spend(session, b, now)
                if spend < b.limit_nanos:
                    continue
                if b.enforcement == "hard" and deny is None:
                    deny = {"budget": b, "spend": spend, "kind": kind}
                    continue
                if b.enforcement == "soft":
                    # alert once per (run, budget) and allow the work to continue
                    await raise_alert(
                        session,
                        tenant_id=self.tenant_id,
                        kind="budget_soft",
                        severity="warning",
                        message=(
                            f"soft budget '{b.name}' reached: spend {format_usd(spend)} >= cap "
                            f"{format_usd(b.limit_nanos)}"
                        ),
                        run_id=self.run_id,
                        agent_id=self.agent_id,
                        context={
                            "budget_id": b.id,
                            "spend_nanos": spend,
                            "limit_nanos": b.limit_nanos,
                        },
                    )

            # Prepaid balance (Phase 4): refuse if this action would overdraw an enforced wallet,
            # otherwise reserve the estimate against available funds (online charging).
            if deny is None:
                wallet = (
                    await session.execute(select(Wallet).where(Wallet.tenant_id == self.tenant_id))
                ).scalar_one_or_none()
                if wallet is not None and wallet.enforce_balance:
                    available = wallet.balance_nanos - wallet.reserved_nanos
                    if available - estimate_nanos < 0:
                        deny = {"wallet": wallet}
                    elif estimate_nanos > 0 and seq is not None:
                        wallet.reserved_nanos += estimate_nanos
                        self.holds[seq] = self.holds.get(seq, 0) + estimate_nanos

        if deny is None:
            return
        if "budget" in deny:
            await self._deny_hard(deny["budget"], deny["spend"], kind)
        raise BudgetExceededError(
            f"insufficient wallet balance ({format_usd(deny['wallet'].balance_nanos)})"
        )

    def take_hold(self, seq: int | None) -> int:
        """Pop the reservation made for ``seq`` (0 if none) so the real debit can release it."""
        if seq is None:
            return 0
        return self.holds.pop(seq, 0)

    async def release_all(self) -> None:
        """Release any reservations still outstanding (steps that errored before debiting)."""
        if not self.holds:
            return
        total = sum(self.holds.values())
        self.holds.clear()
        if total <= 0:
            return
        async with tenant_session(self.tenant_id) as session:
            wallet = (
                await session.execute(select(Wallet).where(Wallet.tenant_id == self.tenant_id))
            ).scalar_one_or_none()
            if wallet is not None:
                wallet.reserved_nanos = max(0, wallet.reserved_nanos - total)

    async def _deny_hard(self, budget: Budget, spend: int, kind: str) -> None:
        """Log the hard-cap alert in its own committed transaction, then raise."""
        async with tenant_session(self.tenant_id) as session:
            await raise_alert(
                session,
                tenant_id=self.tenant_id,
                kind="budget_hard",
                severity="critical",
                message=(
                    f"hard budget '{budget.name}' hit: spend {format_usd(spend)} >= cap "
                    f"{format_usd(budget.limit_nanos)} — stopping agent"
                ),
                run_id=self.run_id,
                agent_id=self.agent_id,
                context={
                    "budget_id": budget.id,
                    "scope": budget.scope,
                    "period": budget.period,
                    "spend_nanos": spend,
                    "limit_nanos": budget.limit_nanos,
                    "action_kind": kind,
                },
            )
        log.warning(
            "credit.denied",
            budget=budget.name,
            spend_nanos=spend,
            limit_nanos=budget.limit_nanos,
            run_id=self.run_id,
        )
        raise BudgetExceededError(
            f"hard budget '{budget.name}' reached "
            f"({format_usd(spend)} / {format_usd(budget.limit_nanos)})"
        )

    async def _period_spend(self, session, budget: Budget, now: datetime) -> int:
        start = _period_start(budget.period, now)
        stmt = select(func.coalesce(func.sum(LedgerEntry.price_nanos), 0)).where(
            LedgerEntry.tenant_id == self.tenant_id,
            LedgerEntry.entry_type == "usage",
        )
        if budget.scope == "agent":
            stmt = stmt.where(LedgerEntry.agent_id == budget.scope_id)
        if start is not None:
            stmt = stmt.where(LedgerEntry.created_at >= start)
        return int((await session.execute(stmt)).scalar_one())
