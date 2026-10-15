# Threat model — Phase 5 (scale & reliability)

Phase 5 adds durability, replay, fair scheduling, multi-provider failover, and backup/restore. None
of these move money (that was Phase 4), but each is a new way the **accounting core** could be
corrupted *at scale or under failure*: a replay that double-charges, a tenant that starves others, a
failover that mis-attributes or loses usage, a backup that leaks another tenant's data, a restore
that silently loses committed spend. Scope: the durable event log + replay, the fair scheduler, the
model router, and backup/restore. Companion record: [ADR-0011](adr/0011-scale-reliability.md). Builds
on the Phase 3 and Phase 4 models.

## Assets

- **Exactly-once accounting under failure** — a worker kill, a provider outage, or an operator replay
  must never create a second ledger entry for one event, nor drop one.
- **The durable stream (`event_log`)** — a faithful, replayable record of captured usage; it must
  agree with the usage events and stay tenant-isolated.
- **Fair capacity** — no tenant can deny service to another by flooding the run queue.
- **Backups** — a snapshot contains every tenant's data; it must be access-controlled like the DB
  itself, and a restore must recover committed state, not a torn copy.
- **Provider attribution** — after a failover, the usage event must name the provider that actually
  served, so cost reconciles against the right bill.

## Trust boundaries

1. Client → API (API key, ADR-0004); the `/v1/ops` endpoints are all tenant-scoped.
2. Operator → CLI (`replay`, `backup`, `restore`) — local, privileged; runs with DB credentials.
3. Runtime/relay → durable log → (future) Kafka — the outbox row is written in the capture
   transaction; a relay ships it onward at-least-once, and the idempotent consumer absorbs dupes.
4. Router → external providers — a provider can fail, hang, or return errors; the router must degrade,
   not corrupt.

## Threats and mitigations (STRIDE-ish)

| # | Threat | Mitigation |
|---|--------|------------|
| T20 | **Replay double-charges** (an operator replays the stream and every event is re-rated) | Rating is idempotent: the ledger is unique on `(tenant_id, usage_event_id)` and `rate_existing_event` is a no-op for an already-rated event. Replay of a healthy stream posts **zero** new entries; `exactly_once` holds because new entries only ever equal repaired gaps. Proven in `test_stream_replay`, `test_chaos`, and the smoke run. |
| T21 | **Lost usage after a crash** (a step is captured but the process dies before rating) | The outbox row is written in the **same transaction** as the usage event, so the gap is always recorded; replay repairs it **exactly once** (`test_chaos`). No silent revenue loss. |
| T22 | **Outbox disagrees with captures** (a phantom logged event, or a missing one) | Transactional outbox: the `event_log` row commits atomically with the `usage_event`. A replay that can't find a referenced usage event skips it (no effect), so even a torn write can't inject a charge. |
| T23 | **Noisy-tenant starvation** (one tenant floods the run queue and others get no service) | The `FairScheduler` caps each tenant's in-flight runs below the global cap and admits waiters round-robin; the Arq path partitions the queue per tenant. A flood tops out at the per-tenant cap, leaving capacity for everyone else (`test_fair_scheduler`). |
| T24 | **Failover mis-attributes or loses usage** (the primary fails mid-request; the event is dropped or billed to the wrong provider) | The router attributes the usage event to `last_provider`/`last_model` — whoever actually served — and metering is still exactly-once on the deterministic idempotency key, so a retry after failover doesn't double-charge (`test_chaos`). |
| T25 | **Router hammers a down provider** (repeated timeouts amplify an outage / run up cost) | The `ProviderHealth` circuit breaker opens after N consecutive failures and deprioritises that provider for a cooldown, while still allowing a half-open retry so recovery is automatic (`test_provider_router`). |
| T26 | **Cross-tenant leak via ops/replay** (one tenant replays or reads another's stream) | `event_log` and `consumer_offset` are tenant-scoped under `FORCE ROW LEVEL SECURITY` (migration `0006`); every `/v1/ops` query runs in the caller's `tenant_session`; replay only ever touches the caller's tenant. |
| T27 | **Backup exfiltration** (a snapshot is a full-fleet data dump) | Backups are produced only by the local operator CLI with DB credentials and are written to operator-controlled storage; they are not exposed over the API. Treat a backup file with the same controls as the database (encrypt at rest, restrict access). *(Operational control, not enforced in code.)* |
| T28 | **Torn / lossy restore** (restore recovers a corrupt or stale copy) | SQLite uses the online-backup API (a consistent snapshot) and an atomic file swap; Postgres uses `pg_dump`/`pg_restore`. The restore path is tested end to end (`test_dr`); RPO/RTO are bounded and documented (runbook-dr.md). |
| T29 | **Replica serves stale data for a decision that writes** (read a lagging replica, then act) | `read_session` is for lag-tolerant reads only (reporting/ops); all credit-control and money paths read the **primary**. The seam defaults to the primary when no replica is configured. |

## Residual risk / follow-ups

- **At-least-once relay to Kafka** is the intended scale path; until the relay exists, the durable log
  is the in-DB outbox. The consumer's idempotency is what makes at-least-once safe — keep it so.
- **Backup encryption/retention** is an operational control, not yet enforced by tooling.
- **Mid-stream provider failure** (after the first token) is surfaced as a run error, not failed over;
  only request-time failures fail over.
- **Load/chaos are proven in-process and in the smoke run**, not yet in a multi-node cluster with real
  Kafka and injected network partitions — that harness is follow-up.
- **RLS is enforced only on Postgres** (migration `0006`); the SQLite dev-fallback mirrors scoping in
  app code — validate isolation on the Postgres stack.
