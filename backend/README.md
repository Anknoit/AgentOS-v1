# AgentOS backend

The FastAPI control plane. One codebase, two deployment modes: the local sidecar that Electron
spawns, and the cloud multi-tenant service. The client points at a configurable backend URL and
never assumes which it talks to.

## Run profiles

| | DB | Runtime | Bus | Needs |
|---|---|---|---|---|
| **Dev fallback** (default) | SQLite (`aiosqlite`) | in-process | in-process | nothing |
| **Full stack** | Postgres (+ RLS) | Arq workers (Redis) | NATS | Docker |

The profile is chosen by env (`AGENTOS_DATABASE_URL`, `AGENTOS_REDIS_URL`, `AGENTOS_BUS`). See
`.env.example` and `docs/adr/0006-dev-db-fallback.md`.

## Quickstart (dev fallback — no external services)

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest                      # 13 tests, all offline
uv run agentos serve               # http://127.0.0.1:8787
# Swagger UI:        http://127.0.0.1:8787/v1/docs
# Prometheus:        http://127.0.0.1:8787/metrics
# Dev API key:       dev-local-key   (Authorization: Bearer dev-local-key)
```

Try the Phase 0 agent-loop spike:

```bash
curl -s -H "Authorization: Bearer dev-local-key" -H "X-Trace-Id: demo-1" \
  -H "Content-Type: application/json" -d '{"task":"hello"}' \
  http://127.0.0.1:8787/v1/runs/sync
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/usage
```

## Full Postgres stack (RLS + workers)

```bash
docker compose -f ../infra/docker-compose.yml up -d        # postgres, redis, nats
export AGENTOS_DATABASE_URL=postgresql+asyncpg://agentos:agentos@localhost:5432/agentos
export AGENTOS_REDIS_URL=redis://localhost:6379/0
uv run alembic upgrade head        # creates schema + switches on row-level security
uv run agentos serve               # API
uv run agentos worker              # Arq worker (separate process)
```

## Layout

```
app/
  config/     settings (pydantic-settings)
  core/       context, logging, tracing (OTel), errors, security, auth, metrics, middleware
  db/         engine, tenant-scoped sessions, base models, Alembic migrations (RLS), seed
  models/     tenant, user, api_key, usage_event        (grows each phase)
  schemas/    Pydantic request/response DTOs
  api/v1/     versioned routers: meta, runs, usage
  runtime/    LLM providers, the agent loop, the Arq queue seam
  metering/   event-bus seam + idempotent usage capture
  connectors/ (Phase 2)  billing/ (Phase 4)  ws/ (streaming)
  main.py     app factory   cli.py   bootstrap.py
tests/        offline test suite
```

## Invariants honored (Phase 0)

- `tenant_id` on every tenant-scoped row; **Postgres RLS** enforces isolation at the data layer
  (migration `0001_initial`), mirrored by app-layer scoping on the SQLite fallback.
- Every `usage_event` carries an **idempotency key**; capture dedupes on `(tenant_id, key)`.
- One trace id spans **client → API → worker → provider call** (W3C traceparent across the queue).
- Observability (structured logs, OTel traces, Prometheus metrics) wired before features.
