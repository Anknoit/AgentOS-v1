# ADR-0003: Usage store — Postgres table for v0

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 0

## Context

`usage_event` is one of the three tables at the heart of the moat. It is written on every
billable action (Phase 1 onward) and read for rating (Phase 3) and spend analytics. The plan
names **ClickHouse** as the scale target (columnar, high-volume aggregation) with **Timescale**
as a Postgres-native alternative. Expected volume decides it — and early on, volume is low.

## Decision

Store `usage_event` in a **Postgres table** for v0 (introduced Phase 1, rated Phase 3). Keep
all writes behind `metering/` and all reads behind spend/query services so the physical store
can move without touching callers. Migrate to ClickHouse or Timescale in Phase 5 when metering
volume justifies a columnar/time-series store.

## Options considered

- **Postgres table** — one store for config, ledger, tenancy, and usage; transactional writes
  alongside the ledger; RLS gives tenant isolation for free. Cost: not built for billions of
  rows or heavy columnar aggregation. Fine at v0 volume.
- **ClickHouse** — the scale endgame for usage analytics. Cost: a separate store to operate and
  keep consistent with Postgres; premature now.
- **Timescale** — stays in the Postgres world (hypertables, continuous aggregates). A likely
  intermediate step before ClickHouse.

## Consequences

- `usage_event` participates in normal Postgres transactions and RLS in v0 — simplest possible
  exactly-once story alongside the ledger.
- **Reversal cost:** moderate. The physical move is hidden behind the metering read/write
  seam; the real work at Phase 5 is dual-write/backfill and re-pointing analytics queries.
