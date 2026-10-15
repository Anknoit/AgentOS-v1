# Runbook — backup, restore & disaster recovery (Phase 5)

This is the operational companion to [ADR-0011](adr/0011-scale-reliability.md). It covers how
AgentOS is backed up, how a restore is performed and verified, the recovery objectives, and the
reliability levers (replay, scheduler, failover) an operator reaches for during an incident.

## Recovery objectives

| Objective | Target | How it's met |
|---|---|---|
| **RPO** (max data loss) | ≤ backup interval; ~0 on managed Postgres | Scheduled `agentos backup`; on Postgres, continuous WAL archiving / PITR closes the gap to near-zero. The durable `event_log` means in-flight usage is recoverable by **replay** even between backups. |
| **RTO** (max downtime) | minutes (single node) | `agentos restore` from the latest snapshot, then `alembic upgrade head`, then start the API. Restore time is dominated by DB size. |
| **Exactly-once after recovery** | always | Rating is idempotent; after a restore (or a worker kill, or a provider outage) `agentos replay <tenant>` re-feeds the stream, repairing any unrated gap **exactly once** and charging nothing twice. |

## Backup

```bash
# SQLite dev-fallback: a consistent snapshot via SQLite's online-backup API.
agentos backup --dest /backups/agentos-$(date -u +%Y%m%dT%H%M%SZ).sqlite

# Postgres (prod): custom-format archive via pg_dump (AGENTOS_DATABASE_URL is read from env).
agentos backup --dest /backups/agentos-$(date -u +%Y%m%dT%H%M%SZ).dump
```

- Schedule it (cron/systemd timer) at the cadence your RPO requires.
- A backup is a **full-fleet** data dump — store it encrypted, with the same access controls as the
  database itself (threat T27).
- On managed Postgres, prefer the provider's PITR/WAL archiving as the primary mechanism and use
  `pg_dump` snapshots as portable, point-in-time exports.

## Restore (and verify)

> Destructive: a restore replaces current data. Quiesce writers first.

```bash
# 1. Stop the API/workers (no writers holding the DB).
# 2. Restore the snapshot (the CLI disposes the engine before swapping the SQLite file / pg_restore).
agentos restore /backups/agentos-20261015T120000Z.sqlite

# 3. Bring the schema to head (no-op if the snapshot was already current).
alembic upgrade head

# 4. Start the API, then verify integrity per tenant:
agentos replay <tenant_id>          # exactly_once=true, new_ledger_entries=0  => healthy
#   (any repaired>0 means a gap was recovered — expected after a crash, benign after a clean restore)
```

Then spot-check reconciliation (`GET /v1/billing/reconciliation`): `balance_drift` and
`gateway_drift` should be within tolerance. The restore path is exercised in CI
(`backend/tests/test_dr.py`): populate → snapshot → corrupt → restore → verify the ledger
re-derives — so "tested restore" is not aspirational.

## Reliability levers during an incident

- **Metering ingestion health** — `GET /v1/ops/stream` shows the durable stream head, event count,
  consumer offset, and lag. Rising lag means the rating consumer is behind.
- **Replay / recovery** — `POST /v1/ops/replay` (or `agentos replay <tenant>`) safely re-processes
  the stream; it is idempotent, so it is safe to run any time and repairs gaps exactly once.
- **Fair scheduling / backpressure** — `GET /v1/ops/scheduler` shows the global and per-tenant
  concurrency caps and this tenant's running/waiting counts. Tune with `AGENTOS_RUN_MAX_CONCURRENCY`
  and `AGENTOS_RUN_PER_TENANT_CONCURRENCY`; on Arq, run one worker per `arq:runs:<n>` partition.
- **Provider failover** — `GET /v1/ops/providers` shows which providers are healthy vs. circuit-open.
  Enable with `AGENTOS_PROVIDER_FAILOVER=true` and
  `AGENTOS_PROVIDER_CANDIDATES='["openai:gpt-4o-mini","anthropic:claude-haiku-4-5"]'` (cheapest
  healthy candidate wins; the router fails over on a request-time error).

## High availability (Postgres path)

- **Read replicas:** set `AGENTOS_READ_REPLICA_URL` to route lag-tolerant reads (reporting/ops) off
  the primary. All credit-control and money paths deliberately read the primary (threat T29).
- **Workers:** run multiple Arq workers across the per-tenant queue partitions so one tenant's burst
  can't monopolise a worker (ADR-0011 §1).
- **Event bus at scale:** move the bus to Kafka (`AGENTOS_BUS=kafka`); the durable outbox is the
  relay source, and the idempotent consumer keeps exactly-once across broker redelivery.
