"""The append-only ledger and the wallet projection — and exactly-once rating."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.session import system_session, tenant_session
from app.metering.pipeline import record_usage
from app.metering.usage import UsageRecord
from app.models.ledger_entry import LedgerEntry
from app.models.tenant import Tenant
from app.models.wallet import Wallet


async def _tenant_id() -> str:
    async with system_session() as s:
        return (await s.execute(select(Tenant).limit(1))).scalar_one().id


def test_run_posts_ledger_and_debits_wallet(client, auth_headers):
    agent = client.post(
        "/v1/agents", headers=auth_headers, json={"name": "Desk", "template": "support_desk"}
    ).json()
    run = client.post(
        f"/v1/agents/{agent['id']}/runs", headers=auth_headers, json={"task": "I need a refund"}
    ).json()
    assert run["status"] == "completed"

    # Spend for this run is the sum of its rated usage (a tool call + a model call).
    spend = client.get(f"/v1/spend?run_id={run['id']}", headers=auth_headers).json()
    assert spend["event_count"] == 2
    kinds = {e["event_type"] for e in spend["by_event_type"]}
    assert kinds == {"tool_call", "model_call"}
    assert spend["price_nanos"] > 0
    # BYO default card: price == cost (reconciles with provider numbers exactly).
    assert spend["price_nanos"] == spend["cost_nanos"]

    # The wallet is a projection of the whole ledger: balance == -(tenant total spend) in BYO mode.
    # (The test DB is shared across the session, so compare against the tenant total, not one run.)
    total = client.get("/v1/spend", headers=auth_headers).json()
    wallet = client.get("/v1/wallet", headers=auth_headers).json()
    assert wallet["balance_nanos"] == -total["price_nanos"]
    assert total["price_nanos"] >= spend["price_nanos"]


@pytest.mark.asyncio
async def test_rating_is_exactly_once(client):
    """A replayed usage event (same idempotency key) posts at most one ledger entry."""
    tenant_id = await _tenant_id()
    rec = UsageRecord(
        tenant_id=tenant_id,
        idempotency_key="replay-run:step9:model_call",
        event_type="model_call",
        provider="mock",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=200,
        run_id="replay-run",
    )
    async with tenant_session(tenant_id) as s:
        first = await record_usage(s, rec)
    async with tenant_session(tenant_id) as s:
        second = await record_usage(s, rec)
    assert first.id == second.id

    async with tenant_session(tenant_id) as s:
        ledger_count = (
            await s.execute(
                select(func.count())
                .select_from(LedgerEntry)
                .where(LedgerEntry.usage_event_id == first.id)
            )
        ).scalar_one()
        # the single entry's price
        entry = (
            await s.execute(select(LedgerEntry).where(LedgerEntry.usage_event_id == first.id))
        ).scalar_one()
        wallet = (
            await s.execute(select(Wallet).where(Wallet.tenant_id == tenant_id))
        ).scalar_one()
    # Exactly one ledger entry for the replayed event, and the wallet reflects a single debit.
    assert ledger_count == 1
    assert entry.price_nanos > 0
    assert wallet.balance_nanos <= -entry.price_nanos
