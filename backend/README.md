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
uv run pytest                      # 68 tests, all offline
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
  models/     tenant, user, api_key, usage_event, agent, agent_version, run, action_log, credential,
              rate_card, ledger_entry, wallet, budget, alert, payment, invoice
  schemas/    Pydantic request/response DTOs
  api/v1/     versioned routers: meta, agents, runs, usage, connectors,
              spend/wallet/budgets/alerts, billing (topups/payments/reconciliation) + invoices
  runtime/    LangGraph kernel + checkpointer, built-in tools, templates, run manager,
              LLM providers, the Phase 0 agent-loop spike, the Arq queue seam, usage store
  connectors/ MCP-first connector framework: capabilities, specs, MCP client + sessions,
              registry, broker (scope enforcement), built-in Slack/CRM/HTTP + generic MCP
  services/   agent CRUD + versioning, run trigger/resume, connector discovery, credential vault,
              rate cards, spend aggregation, budgets, wallet enforcement
  metering/   money (nanodollars), rating engine, pipeline (capture→rate→ledger→wallet→anomaly),
              credit control (budgets + prepaid reserve/hold), anomaly detection, idempotent capture
  billing/    (Phase 4) Razorpay gateway (+ mock), top-up lifecycle, wallet credits/reserve,
              invoicing engine, reconciliation
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

## Metering, rating & budgets (Phase 3)

Every billable step (model, tool, connector) is captured, **rated** against the active rate card,
and posted to an **append-only ledger** in the same transaction (ADR-0009). Money is exact integer
nanodollars; the wallet is a cached projection of the ledger. A **hard budget stops an agent at its
cap** (online credit control); a soft budget alerts.

```bash
# set a hard cap on an agent, run it, and watch it stop at the limit
curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"name":"cap","scope":"agent","scope_id":"'$AID'","limit_usd":"0.0005","enforcement":"hard"}' \
  http://127.0.0.1:8787/v1/budgets
# rated spend — per run, per agent, and the tenant total (cost == price in BYO, markup 0)
curl -s -H "Authorization: Bearer dev-local-key" "http://127.0.0.1:8787/v1/spend?run_id=$RID"
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/spend/agents
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/wallet
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/rate-cards
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/alerts
```

A run blocked by a hard cap finalizes with status `stopped` (not `failed`), logs a `budget_hard`
alert, and leaves its checkpoint intact so it can resume if the cap is raised.

## Settlement & payments (Phase 4)

AgentOS becomes the payer: a tenant tops up a **prepaid wallet** through **Razorpay**, usage debits
it as agents run (Phase 3 metering), and one itemized **invoice** rolls the ledger (ADR-0010). A
top-up is confirmed by HMAC-SHA256 signature on both the checkout callback and the webhook, and is
credited to the wallet **exactly once** (ledger movements are unique on `(tenant_id, ref)`). Money-in
runs on the dev/test profile against an in-process mock gateway that signs with the dev key secret,
so the full flow works offline. Set `AGENTOS_PAYMENT_PROVIDER=razorpay` (+ `AGENTOS_RAZORPAY_KEY_ID`
/ `_KEY_SECRET` / `_WEBHOOK_SECRET`) for the live gateway.

```bash
# 1. create a $25 top-up order (returns Razorpay order_id + key_id for checkout)
curl -s -H "Authorization: Bearer dev-local-key" -H "Content-Type: application/json" \
  -d '{"amount_usd":"25"}' http://127.0.0.1:8787/v1/billing/topups
# 2. the client opens Razorpay checkout; on success it posts the signed callback back:
#    POST /v1/billing/topups/{order_id}/confirm {razorpay_payment_id, razorpay_signature}
#    (the webhook POST /v1/webhooks/razorpay reconciles the same payment — credited once)
# 3. run a mixed fleet, then roll one invoice across all agents and reconcile the ledger
curl -s -H "Authorization: Bearer dev-local-key" -X POST \
  -H "Content-Type: application/json" -d '{}' http://127.0.0.1:8787/v1/invoices
curl -s -H "Authorization: Bearer dev-local-key" http://127.0.0.1:8787/v1/billing/reconciliation
# 4. enter the prepaid path — a depleted balance then stops billable work
curl -s -H "Authorization: Bearer dev-local-key" -X PATCH \
  -H "Content-Type: application/json" -d '{"enforce_balance":true}' http://127.0.0.1:8787/v1/wallet
```

With prepaid enforcement on, credit control reserves each action's estimate against **available**
funds (`balance − reserved`) and the real debit releases the hold, so a concurrent burst can't
overrun; a depleted balance stops the run `stopped`. Reconciliation re-derives the balance from the
ledger and flags drift (critical `reconciliation_drift` alert) so margin never silently leaks.

## Invariants honored (Phases 0–4)

- `tenant_id` on every tenant-scoped row; **Postgres RLS** enforces isolation at the data layer
  (migrations `0001`–`0005` — now also `rate_card`, `ledger_entry`, `wallet`, `budget`, `alert`,
  `payment`, `invoice`), mirrored by app-layer scoping on the SQLite fallback.
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
- **Money is exact.** Every rated event posts one immutable `ledger_entry` (unique on
  `(tenant_id, usage_event_id)`), priced in integer nanodollars against a versioned rate card;
  balances are projections, rating is exactly-once, and a hard budget stops an agent at its cap —
  **checked before each billable action** (ADR-0009).
- **Settlement is exact and idempotent.** Top-ups/refunds are ledger movements unique on
  `(tenant_id, ref)`, so the checkout callback and the webhook credit a wallet **exactly once**; a
  gateway signature is HMAC-verified before any money moves; a prepaid balance reserves against
  in-flight work and a depleted balance stops billable work; reconciliation surfaces drift (ADR-0010).
- Observability (structured logs, OTel traces, Prometheus metrics) wired before features.
