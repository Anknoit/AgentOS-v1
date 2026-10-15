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
uv run pytest                      # 41 tests, all offline
uv run agentos serve               # http://127.0.0.1:8787
# Swagger UI:        http://127.0.0.1:8787/v1/docs
# Prometheus:        http://127.0.0.1:8787/metrics
# Dev API key:       dev-local-key   (Authorization: Bearer dev-local-key)
```

Run a Support Desk agent end to end (Phase 1):

```bash
AUTH='-H "Authorization: Bearer dev-local-key"'
# 1. create an agent from the Support Desk template
AID=$(curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"name":"Help Desk","template":"support_desk"}' \
  http://127.0.0.1:8787/v1/agents | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
# 2. run it against a task (returns the completed run)
RID=$(curl -s -H "Authorization: Bearer dev-local-key" -H "X-Trace-Id: demo-1" \
  -H "Content-Type: application/json" -d '{"task":"I need a refund"}' \
  http://127.0.0.1:8787/v1/agents/$AID/runs | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
# 3. inspect the complete audit log and the usage events it generated
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/runs/$RID/actions
curl -s -H "Authorization: Bearer dev-local-key" "http://127.0.0.1:8787/v1/usage?run_id=$RID"
```

The Phase 0 agent-loop spike is still available at `POST /v1/runs/sync` and `WS /v1/runs/stream`.

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
  core/       context, logging, tracing (OTel), errors, security, crypto, auth, metrics, middleware
  db/         engine, tenant-scoped sessions, base models, Alembic migrations (RLS), seed
  models/     tenant, user, api_key, usage_event, agent, agent_version, run, action_log, credential
  schemas/    Pydantic request/response DTOs
  api/v1/     versioned routers: meta, agents, runs, usage, connectors
  runtime/    LangGraph kernel + checkpointer, built-in tools, templates, run manager,
              LLM providers, the Phase 0 agent-loop spike, the Arq queue seam, usage store
  connectors/ MCP-first connector framework: capabilities, specs, MCP client + sessions,
              registry, broker (scope enforcement), built-in Slack/CRM/HTTP + generic MCP
  services/   agent CRUD + versioning, run trigger/resume, connector discovery, credential vault
  metering/   event-bus seam + idempotent usage capture
  billing/    (Phase 4)  ws/ (streaming)
  main.py     app factory   cli.py   bootstrap.py
tests/        offline test suite
```

## Connectors (Phase 2)

Agents reach real systems through **MCP connectors** with permissions and credentials as scoped,
tenant-isolated objects (ADR-0008). Discover connectors, store a credential (encrypted per
tenant), then deploy the connected Support Desk:

```bash
# discover connectors + their tools/scopes
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/connectors
# store credentials (secret is write-only — never returned)
curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"connector_key":"crm","secret":"crm-key","provider_meta":{"instance":"acme"}}' \
  http://127.0.0.1:8787/v1/credentials
curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"connector_key":"slack","secret":"xoxb-token","provider_meta":{"workspace":"acme"}}' \
  http://127.0.0.1:8787/v1/credentials
# create a Support Desk agent wired to Slack + CRM, run it, inspect the connector calls
AID=$(curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"name":"Connected Desk","template":"support_desk_connected"}' \
  http://127.0.0.1:8787/v1/agents | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
RID=$(curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"task":"I need a refund"}' http://127.0.0.1:8787/v1/agents/$AID/runs \
  | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/runs/$RID/actions
```

The `action_log` shows each `connector_call` (granted and denied); an ungranted scope is denied
and logged. Connect any **third-party MCP server** via the generic `mcp` connector (store a
credential whose `provider_meta.url` is the server URL).

## Invariants honored (Phases 0–2)

- `tenant_id` on every tenant-scoped row; **Postgres RLS** enforces isolation at the data layer
  (migrations `0001`, `0002` — now also `agent`, `agent_version`, `run`, `action_log`), mirrored
  by app-layer scoping on the SQLite fallback.
- **Config is data, versioned.** `agent_version` is immutable; a run pins the exact version it
  executed, so behaviour is reproducible and a bad change rolls back.
- **Agents run as managed jobs.** A run executes off the request path (in-process manager or Arq
  worker), survives client disconnect, and is **resumable from its LangGraph checkpoint** across a
  worker restart (ADR-0007).
- Every billable step (model call **and** tool call) captures a `usage_event` with a
  **deterministic idempotency key** (`{run_id}:step{seq}:{kind}`); a replayed step never
  double-counts. The `action_log` is append-only and idempotent on `(run_id, seq)`.
- One trace id spans **client → API → worker → provider call** (W3C traceparent across the queue).
- **Connectors are MCP servers behind one session**; the `ConnectorBroker` is the single point
  that checks an agent's scoped grant **before** a credential is loaded, meters a `connector_call`
  usage event, and audits the call — a denied scope is refused and logged (ADR-0008).
- **Connector secrets are encrypted per tenant** (HKDF-derived Fernet key), decrypted only at call
  time, never returned by the API, never logged.
- Observability (structured logs, OTel traces, Prometheus metrics) wired before features.
