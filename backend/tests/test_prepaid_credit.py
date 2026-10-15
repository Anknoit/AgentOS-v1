"""Prepaid online credit control (Phase 4): reserve against *available* balance, deny when a
depleted balance can't cover the next action, and never leak a reservation.

These run on a freshly-created tenant with a precisely-set wallet, so the assertions are exact and
independent of the shared test DB. The clean-DB end-to-end (an agent actually stopping) is covered
by the desktop sidecar smoke test; here we prove the controller logic the kernel relies on.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.billing.wallet_ops import get_or_create_wallet
from app.config import get_settings
from app.core.errors import BudgetExceededError
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session, tenant_session
from app.metering.credit import CreditController
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.models.user import User
from app.models.wallet import Wallet
from app.services.ratecards import ensure_default_card


async def _new_tenant(slug: str) -> str:
    s = get_settings()
    async with system_session() as session:
        tenant = Tenant(slug=slug, name=slug)
        session.add(tenant)
        await session.flush()
        tid = tenant.id
        user = User(tenant_id=tid, email=f"{slug}@t.local", role="owner")
        session.add(user)
        await session.flush()
        session.add(
            ApiKey(
                tenant_id=tid,
                user_id=user.id,
                name="k",
                prefix=key_prefix(f"key-{slug}"),
                key_hash=hash_api_key(f"key-{slug}", pepper=s.api_key_pepper),
            )
        )
    await ensure_default_card(tid)
    return tid


async def _fund(tid: str, balance_nanos: int) -> None:
    async with tenant_session(tid) as session:
        wallet = await get_or_create_wallet(session, tid)
        wallet.balance_nanos = balance_nanos
        wallet.enforce_balance = True


async def _reserved(tid: str) -> int:
    async with tenant_session(tid) as session:
        wallet = (
            await session.execute(select(Wallet).where(Wallet.tenant_id == tid))
        ).scalar_one()
        return wallet.reserved_nanos


@pytest.mark.asyncio
async def test_authorize_reserves_then_denies_when_available_exhausted(client):
    tid = await _new_tenant("prepaid-deny")
    await _fund(tid, 1_000)  # 1000 nanos available

    cc = CreditController(tenant_id=tid, agent_id="a1", run_id="r1")
    # First action fits (600 <= 1000) and reserves against available.
    await cc.authorize(kind="model_call", estimate_nanos=600, seq=1)
    assert await _reserved(tid) == 600

    # Second action does not fit: available is now 1000 - 600 = 400 < 600 -> stop.
    with pytest.raises(BudgetExceededError):
        await cc.authorize(kind="model_call", estimate_nanos=600, seq=2)
    # The denied action reserved nothing.
    assert await _reserved(tid) == 600

    # Releasing the run's holds returns the reservation (no leak).
    await cc.release_all()
    assert await _reserved(tid) == 0


@pytest.mark.asyncio
async def test_depleted_balance_denies_next_action(client):
    """An empty wallet refuses any priced action; an overdrawn one refuses even a free step."""
    tid = await _new_tenant("prepaid-empty")

    # Exactly zero balance: a priced action (estimate > available) is refused.
    await _fund(tid, 0)
    cc = CreditController(tenant_id=tid, run_id="r1")
    with pytest.raises(BudgetExceededError):
        await cc.authorize(kind="tool_call", estimate_nanos=1, seq=1)

    # Once a prior debit has driven the balance negative, even a zero-estimate step stops.
    await _fund(tid, -1)
    cc2 = CreditController(tenant_id=tid, run_id="r2")
    with pytest.raises(BudgetExceededError):
        await cc2.authorize(kind="tool_call", estimate_nanos=0, seq=1)


@pytest.mark.asyncio
async def test_enforcement_off_never_reserves_or_denies(client):
    """BYO default (enforcement off): the balance can go negative and nothing is reserved."""
    tid = await _new_tenant("byo-tenant")
    async with tenant_session(tid) as session:
        wallet = await get_or_create_wallet(session, tid)
        wallet.balance_nanos = 0
        wallet.enforce_balance = False
    cc = CreditController(tenant_id=tid, run_id="r1")
    await cc.authorize(kind="model_call", estimate_nanos=10_000, seq=1)  # does not raise
    assert await _reserved(tid) == 0
