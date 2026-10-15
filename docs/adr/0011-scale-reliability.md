# ADR-0011: Scale & reliability — durable stream, fair scheduling, provider failover, HA/DR

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 5
- **Builds on:** [ADR-0001](0001-worker-execution-engine.md) (Arq workers),
  [ADR-0002](0002-event-bus.md) (NATS→Kafka), [ADR-0003](0003-usage-store.md) (usage store),
  [ADR-0009](0009-metering-rating-budgets.md) (exactly-once rating, the ledger),
  [ADR-0006](0006-dev-db-fallback.md) (the swappable-seam + dev-fallback discipline)

## Context

Phases 3–4 made the accounting core correct; Phase 5 must keep it correct and available as agents,
tenants, and event volume grow by orders of magnitude, without rewriting that core. The exit bar is
explicit: a load test sustains **exactly-once metering** within SLA, and **killing a worker or
failing a provider loses or double-counts no usage** (proven with chaos + replay). The constraint is
the same one every prior phase honoured — a dependency only an operator would run at scale (Kafka,
multiple provider accounts, read replicas) must sit behind a seam with a hermetic in-process default
so the whole system still boots, tests, and demos offline.

## Decision

**1. Fair, back-pressured run admission — a per-tenant cap, not just a global one.** A
`FairScheduler` (a fair async semaphore) gates run execution with a **global** in-flight limit
(backpressure) and a **per-tenant** limit, and releases waiters **round-robin** so a flood from one
tenant can neither consume the whole box nor jump ahead of others. In the in-process runtime it
gates `RunManager`; on the Arq path the same intent is a **per-tenant queue partition**
(`arq:runs:<hash(tenant)>`, one worker per partition). The backend changes; the admission contract
does not.

**2. The metering stream is a transactional outbox, durable and replayable.** Every captured usage
event writes a row to the append-only `event_log` **in the same transaction** as the `usage_event`
it records, so the durable stream can never disagree with what was captured (no lost/phantom
events, no second-transaction lock contention). `event_log` is the dev-fallback analogue of a Kafka
topic — a monotonic `offset` PK, a per-tenant consumer cursor in `consumer_offset` — and a relay
ships outbox rows to Kafka at scale behind the unchanged `EventBus` seam. The in-process bus stays
live fan-out only.

**3. Replay is the exactly-once proof *and* the recovery tool.** Because rating is idempotent
(ledger unique on `(tenant_id, usage_event_id)`), re-feeding the stream through the pipeline posts
**nothing** for already-rated events and **repairs** a captured-but-unrated gap exactly once. One
operation (`agentos replay` / `POST /v1/ops/replay`) therefore both proves exactly-once (a healthy
stream replays to zero change) and recovers lost rating after a crash — the chaos exit criterion,
demonstrated deterministically rather than hoped for.

**4. Multi-provider routing with cost-aware selection and failover.** A `ModelRouter` behind the
existing `LLMProvider.stream` contract orders candidates (`provider:model`) cheapest-first among
healthy ones and **fails over** on a request-time provider error; a `ProviderHealth` circuit breaker
deprioritises a repeatedly-failing provider for a cooldown. The usage event is attributed to whoever
actually served (`last_provider`/`last_model`), so metering stays exactly-once and correct **through**
a failover. Off by default (single provider) for back-compat.

**5. HA/DR as scripted, tested operations.** Backup/restore is first-class (`agentos backup` /
`agentos restore`): SQLite via the online-backup API + atomic file swap, Postgres via
`pg_dump`/`pg_restore`. The restore is exercised in CI (populate → snapshot → corrupt → restore →
verify), because an untested restore is not a DR plan. A read-replica routing seam (`read_session`)
offloads lag-tolerant reads, falling back to the primary when unconfigured. RPO/RTO and the runbook
live in [docs/runbook-dr.md](../runbook-dr.md).

**6. Voice/telephony stays deferred.** The plan gates it on demand ("add once demand justifies the
infra"); the capability seam is reserved but no low-latency telephony subsystem ships in Phase 5.

## Options considered

- **Durable stream as a transactional outbox (chosen)** vs. a decorator bus that persists in its own
  transaction — the latter deadlocks on the capturing transaction's write lock (SQLite) and can log
  phantom events for rolled-back captures; the outbox is atomic with the capture and is the standard
  exactly-once-publish pattern.
- **Fair semaphore with a per-tenant cap (chosen)** vs. a single global queue — a global FIFO lets
  one tenant's burst starve everyone behind it; the per-tenant cap bounds any one tenant's share.
- **Router-level failover (chosen)** vs. retry-in-place on one provider — retry can't survive a
  provider outage; cost-aware candidate ordering also captures the "cheapest model that works" goal.
- **ClickHouse/Timescale for the usage store now** — deferred (ADR-0003 leaves it to volume);
  Phase 5 hardens ingestion (outbox + replay) without moving the store yet.

## Consequences

- Exactly-once survives a worker kill (resume from checkpoint, ADR-0007) **and** a provider failure
  (failover + attributed metering) **and** an explicit replay — all proven in the test suite and the
  sidecar smoke run.
- New surface: tenant-scoped `/v1/ops/stream`, `/v1/ops/replay`, `/v1/ops/scheduler`,
  `/v1/ops/providers`; migration `0006` adds `event_log` + `consumer_offset` (RLS); CLI gains
  `replay`, `backup`, `restore`.
- Kafka, per-tenant Arq partitions, a read replica, and multiple provider accounts are all opt-in via
  settings; the zero-dependency dev profile is unchanged.
- **Residual risk / follow-ups:** the outbox→Kafka relay and a scheduled replay/projection-repair job
  are on-demand, not yet periodic; a mid-stream provider failure (after the first token) surfaces as a
  run error rather than failing over; read-replica routing is wired as a seam but only reporting/ops
  reads use it so far; voice is deferred; load/chaos are proven in-process and in the smoke run, not
  yet in a multi-node cluster harness.
- **Reversal cost:** low for the scheduler, router, and DR tooling (isolated modules); moderate for
  the outbox (a new table, but additive and idempotent); the money unit and ledger idempotency are
  untouched.
