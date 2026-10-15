# ADR-0009: Metering, rating & budgets — the accounting core

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 3

## Context

Phase 3 turns captured usage into money: accurate per-agent cost and real-time budgets, **on the
tenant's own provider keys** (BYO), before any payment path. This is the start of the moat, so the
decisions here are load-bearing above almost everything else — the invariants are exactly-once
rating, append-only accounting, and tenant isolation.

Phases 0–2 already capture one `usage_event` per billable action (model, tool, connector) with a
**deterministic idempotency key** (`{run_id}:step{seq}:{kind}`) and publish `usage.captured` onto
the event-bus seam. What Phase 3 adds: pricing, a ledger, a wallet, and credit control.

## Decision

1. **Money is an exact integer — nanodollars.** Every monetary quantity is stored and computed as
   an integer number of nanodollars (1 USD = 1e9 nano). Integers are exact on Postgres *and* the
   SQLite dev-fallback (SQLite's `NUMERIC` affinity can round a float); token prices are sub-cent
   (gpt-4o-mini input is 150 nano/token), so a coarser unit would lose precision on a single token.
   All price→amount math goes through `Decimal` and is quantized to a whole nano exactly once, in
   `app/metering/money.py`.

2. **Rating is pure, deterministic, and versioned (the telecom pattern).** `rate_event(card,
   event)` prices one event against a `rate_card`; given the same inputs it always yields the same
   amounts, so re-rating a replayed event can never drift. A card is **versioned with an effective
   date** and never edited in place — a price change writes a new card, and historical events stay
   priced by the card active when they occurred. The card carries both **cost** (provider charge)
   and **price** (tenant pays) via a markup; Phase 3's default card is `markup=0` (BYO pass-through,
   so rated spend lands on the providers' own numbers), and Phase 4 raises it to turn margin into an
   accounted quantity. A built-in default card (real provider list prices) is the in-code fallback
   so rating always has a card.

3. **Rating runs inline and co-transactional with capture — in v0.** On a single Postgres, pricing
   an event in the **same transaction** that captures it is the simplest way to guarantee
   exactly-once: there is no window where an event is captured but unrated, and no dropped async
   message can double- or under-count. `app/metering/pipeline.record_usage` is the one entry point
   the runtime uses — capture → rate → ledger → wallet → anomaly, all in the caller's transaction.
   The event bus still carries `usage.captured` as the **decoupling seam**: at Kafka scale (Phase 5)
   the rating step moves to an out-of-process consumer behind that same subject, without changing
   the runtime. We chose correctness-now over the distributed pipeline because the moat cannot
   tolerate an accounting race, and the seam keeps the scale path open.

4. **The ledger is append-only; balances are projections.** One immutable `ledger_entry` per rated
   event, attributed to agent + run + tenant, recording both cost and price. Exactly-once is
   enforced at the data layer: `(tenant_id, usage_event_id)` is unique, so a replayed usage event
   posts at most one entry. `wallet.balance_nanos` is a **cached projection** of the ledger, updated
   on each write and always rebuildable by summing it.

5. **Budgets are online credit control — checked *before* each billable action.** A
   `CreditController`, constructed per run with no ambient authority, is called ahead of every
   model, tool, and connector call (the "authorize" half; the ledger debit is the "charge" half). A
   **hard** budget that has reached its limit raises `BudgetExceededError`, which the kernel catches
   to finalize the run as **`stopped`** (not failed) — so an agent runs up to its cap then halts,
   overrunning by at most the one action that crossed the line. A **soft** budget raises an alert
   and lets work continue. Budget scope is `tenant` or `agent`; period is `total`/`daily`/`monthly`.
   Prepaid-balance enforcement is wired here too (`wallet.enforce_balance`) but off while keys are
   BYO — Phase 4 turns it on with top-ups.

6. **Alerts + simple anomaly detection run inline.** `runaway_loop` (a run billing far more steps
   than any sane loop) and `spend_spike` (one event priced far above the run average) are screened
   in the same transaction that rates an event, so an alert is durable, deduped per (run, kind), and
   never lost to a dropped message. Thresholds are deliberately high; tuning/ML is a later phase.

## Options considered

- **Bus-driven, out-of-process rating now.** Most faithful to the "consume off the bus" build task
  and the Phase 5 target. Cost: on one Postgres it introduces a capture-then-rate window and a
  double-/under-count risk under retries, for no scale benefit yet. Rejected *for v0* — adopted
  behind the same bus subject in Phase 5, where throughput justifies it.
- **Store money as `NUMERIC`/`Decimal` columns.** Readable. Cost: SQLite's loose `NUMERIC` affinity
  can silently store a float and round sub-cent token prices. Rejected for exact integer nanodollars.
- **Mutable running-balance row as source of truth.** O(1) reads without a ledger. Cost: no audit
  trail, no way to prove a balance, and a lost update corrupts money. Rejected — append-only ledger
  is the source of truth, the wallet is only its cache.
- **Enforce budgets after the action (post-paid).** Simpler (no pre-check). Cost: an agent can
  overrun its cap arbitrarily before anyone notices. Rejected — online credit control checks before.

## Consequences

- The whole path — capture → rate → ledger → wallet → budget check → alert — runs in CI on SQLite
  with the mock provider, no network. Rated spend equals the provider formula exactly (BYO markup 0),
  so it reconciles within rounding against provider invoices; Phase 4's reconciliation builds on this.
- `connector_call` (ADR-0008) is priced with no new plumbing — it is just another rated event type.
- Exactly-once from ADR-0007 now covers money: a resumed run re-rates nothing (the usage event is
  already `rated`, the ledger entry already exists), so budgets and balances never double-count.
- Rotating prices is a new effective-dated card, never an in-place edit — history stays reproducible.
- A full threat model for this phase lives in [docs/threat-model-phase3.md](../threat-model-phase3.md).
