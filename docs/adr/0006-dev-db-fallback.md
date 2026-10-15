# ADR-0006: Dev DB fallback — SQLite + in-process runtime alongside the Postgres path

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 0

## Context

The real deployment targets (sidecar and cloud) run **Postgres** (with row-level security for
tenant isolation) and **Redis** (Arq workers, credit control). But a contributor — or CI, or a
quick spike — should be able to boot the backend and run the Phase 0 agent-loop spike with
**zero external services**. Requiring Docker/Postgres/Redis just to see `/health` or stream a
token raises the cost of every contribution and every test.

## Decision

Support two run profiles behind the same application code, selected by `DATABASE_URL` /
`REDIS_URL`:

1. **Postgres profile (ships):** `postgresql+asyncpg://…`. Alembic migrations create every
   table **and enable RLS** (`FORCE ROW LEVEL SECURITY` + per-tenant policies). Tenant isolation
   is enforced at the data layer via the `app.current_tenant` session GUC. This is the
   dev-via-compose, single-tenant sidecar, and cloud path.
2. **SQLite dev-fallback (default when no Postgres configured):** `sqlite+aiosqlite://…`.
   Same SQLAlchemy models and schema. SQLite has **no RLS**, so tenant isolation is enforced by
   an application-layer guard (every tenant-scoped query goes through a session bound to the
   request's `tenant_id`, matching what RLS enforces in Postgres). For dev and tests only —
   **never a production target.**

When `REDIS_URL` is unset, the runtime executes the agent loop **in-process** (no Arq worker
needed to boot); with Redis configured, runs are enqueued to Arq.

## Options considered

- **Postgres-only** — one code path, RLS always on. Cost: Docker is mandatory for any local
  work or test; slower contribution loop; blocks verification where Docker is unavailable.
- **SQLite fallback (chosen)** — instant boot, fast tests, verifiable anywhere. Cost: two DB
  dialects to keep schema-compatible, and RLS is only exercised on the Postgres path — so
  tenant-isolation tests must run against Postgres in CI/compose, not SQLite.

## Consequences

- `/health`, auth, the agent-loop WS spike, and `usage_event` writes all run with no external
  services — Phase 0 exit criteria are verifiable offline.
- **RLS is only proven on Postgres.** Tenant-isolation guarantees are validated in the compose/
  CI Postgres profile; the SQLite guard is a convenience mirror, not the security boundary.
- Keep models dialect-portable (avoid Postgres-only column types in the shared schema; put
  Postgres-specific DDL — RLS, partitioning — in migrations, not model definitions).
