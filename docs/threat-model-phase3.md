# Threat model — Phase 3 (metering, rating & budgets)

Phase 3 is the accounting core — the moat. A defect here does not leak a credential (Phase 2's
worst case); it corrupts **money**: mis-bills a tenant, lets an agent overrun its cap, or lets one
tenant's spend bleed into another's. So the core is threat-modelled on its own. Scope: the metering
pipeline, the rating engine, the append-only ledger, the wallet projection, and online credit
control. Companion decision record: [ADR-0009](adr/0009-metering-rating-budgets.md).

## Assets

- **Accounting accuracy** — rated spend must match what actually happened, to the nanodollar, and
  reconcile against provider invoices. This is the product.
- **The ledger** — immutable, complete, and attributable (tenant, agent, run, rate card).
- **Budget enforcement** — a hard cap must actually stop an agent; a tenant must not be able to
  spend past what they are entitled to.
- **Tenant isolation of financial data** — one tenant must never read or affect another's ledger,
  wallet, budgets, or prices.

## Trust boundaries

1. Client → API (API key, ADR-0004); spend/budget endpoints are tenant-scoped.
2. Runtime → database (tenant boundary enforced by Postgres RLS, ADR-0006; now also on
   `rate_card`, `ledger_entry`, `wallet`, `budget`, `alert`).
3. Provider usage numbers → rating (token counts come from the provider response; an inflated count
   over-bills — see T6).
4. Agent/model behaviour → spend (a looping or prompt-injected agent can try to burn budget — T3).

## Threats and mitigations (STRIDE-ish)

| # | Threat | Mitigation |
|---|--------|------------|
| T1 | **Double-billing on retry/resume** (a replayed step rates twice) | Two deterministic keys: `usage_event` dedupes on `(tenant_id, idempotency_key)`; `ledger_entry` dedupes on `(tenant_id, usage_event_id)` (unique). A replayed step finds the event already `rated` and returns — no second entry, no second debit. Rating is pure, so the amount is identical anyway (ADR-0009 §2–4). |
| T2 | **Under-counting / lost usage** (event captured but never rated) | Rating is **inline and co-transactional** with capture (ADR-0009 §3): capture + rate + ledger + wallet commit atomically, so there is no "captured-but-unrated" window and no async message to drop. |
| T3 | **Budget overrun by a runaway/injected agent** | Online credit control checks the budget **before** each billable action; a hard cap stops the run `stopped` at the limit. A `runaway_loop` alert fires if a run bills past a sane step count. Overrun is bounded to the single action that crosses the cap. |
| T4 | **Cross-tenant financial read/write** | Every Phase 3 table is tenant-scoped and under `FORCE ROW LEVEL SECURITY` (migration `0004`); all spend/budget queries filter on `tenant_id`; the wallet is unique per tenant. Mirrored by app-layer scoping on the SQLite fallback. |
| T5 | **Price tampering / wrong price applied** | Rate cards are **versioned and effective-dated**, never edited in place; a historical event is priced by the card active when it occurred, so a later price change can't retroactively re-bill it. Cards are tenant-scoped (RLS). |
| T6 | **Inflated provider token counts over-bill the tenant** | In BYO (Phase 3) cost == what the tenant's own key is charged, so rating mirrors the provider; Phase 4 reconciliation compares metered spend against the provider's actual invoice and **surfaces drift**, catching a systematic inflation. |
| T7 | **Float rounding drift accumulating into real money** | Money is exact integer nanodollars; price→amount math is `Decimal`, quantized once (ADR-0009 §1). No float is ever summed into a balance. |
| T8 | **Ledger tampering / silent balance edit** | The ledger is append-only (no update/delete path in the service layer); the wallet is a derived cache that can be rebuilt from it, so a tampered balance is detectable by re-projection. |
| T9 | **Alert suppression hiding abuse** | Anomaly detection runs **inline** in the rating transaction (not on a best-effort async handler), so an alert is committed with the event it describes and can't be lost to a dropped bus message. |

## Residual risk / follow-ups

- **Budget check vs charge is not yet a reservation.** v0 authorizes on realized spend and debits
  after; a burst of concurrent actions could each pass the check before any debits land, slightly
  overrunning a cap. Phase 4 adds reserve/hold against in-flight work (true online charging) and a
  race test on concurrent debits.
- **Provider reconciliation** (compare metered vs actual provider invoices, surface drift) lands in
  Phase 4 — T6's full mitigation.
- **Wallet projection repair.** A rebuild-from-ledger reconcile job is easy to add; not yet wired as
  a scheduled check.
- **Per-connector/agent rate limiting** beyond spend caps (request velocity) is future work.
- **Out-of-process rating at scale** (Phase 5) must preserve exactly-once across the bus
  (idempotent consumer keyed on `usage_event_id`) — the keys are already in place for it.
