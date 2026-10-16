# shared/ — the API contract

The desktop shell and the web UI (`AgentOS_ui/`) depend on the backend **only** through a
versioned REST + WebSocket API and a generated typed client SDK. This directory holds that
contract so both clients build against a stable surface in parallel.

## `openapi.json`

The backend's OpenAPI 3.1 schema, generated from the FastAPI app. Regenerate after any API
change:

```bash
cd backend
AGENTOS_OTEL_EXPORTER=none uv run python -c \
  "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" \
  > ../shared/openapi.json
```

(The backend also serves it live at `GET /v1/openapi.json`, with Swagger UI at `/v1/docs`.)

## Typed client SDK (generate now — the Phase 1 surface is real)

The Phase 1 API surface (agents CRUD, runs, action log, usage) is stable, so the UI can start
generating a typed client here and replacing `AgentOS_ui/src/lib/agentos/mockData.ts` +
`store.tsx` with real calls:

```bash
npx openapi-typescript shared/openapi.json -o shared/src/api-types.ts
```

plus a thin fetch/WebSocket wrapper that injects `Authorization` and the `X-Trace-Id` header
(so a trace starts on the client and spans client → API → worker).

## WebSocket contract (not in OpenAPI)

**Agent runs** — `WS /v1/agents/{agent_id}/runs/stream`: connect with `?token=<api-key>` (or an
`Authorization: Bearer` header), send `{"task": "..."}`, and receive run-event frames as the run
executes. The run is a managed job — disconnecting does not stop it.

| `type`        | fields |
|---------------|--------|
| `run_started` | `run_id` |
| `node`        | `run_id`, `name`, `seq` |
| `tool_call`   | `run_id`, `name`, `seq`, `results`, `usage_event_id` |
| `token`       | `run_id`, `text` |
| `usage`       | `run_id`, `usage_event_id`, `input_tokens`, `output_tokens`, `total_tokens` |
| `done`        | `run_id`, `output`, `input_tokens`, `output_tokens`, `total_tokens`, `tool_calls` |
| `error`       | `run_id`/none, `message` |

The Phase 0 spike socket `WS /v1/runs/stream` (anonymous, no agent) remains for the token-stream
demo.

## Current surface (Phases 0–6)

- `GET  /health` — liveness + which DB/runtime profile is active, deployment mode + region (unauthenticated)
- `GET  /metrics` — Prometheus metrics (unauthenticated)
- `GET  /v1/whoami` — authenticated tenant context, including the principal's **role** and auth method
- `POST /v1/agents` · `GET /v1/agents` · `GET|PATCH /v1/agents/{id}` — agent CRUD (immutable versions)
- `GET  /v1/agents/{id}/versions` — an agent's config versions
- `POST /v1/agents/{id}/runs` — trigger a run (returns the completed run in-process)
- `WS   /v1/agents/{id}/runs/stream` — trigger + stream run events
- `GET  /v1/runs` · `GET /v1/runs/{id}` — list / inspect runs
- `GET  /v1/runs/{id}/actions` — the append-only action log for a run (incl. `connector_call` rows)
- `POST /v1/runs/{id}/resume` · `POST /v1/runs/{id}/cancel` — lifecycle control
- `GET  /v1/usage` — list captured usage events (filter by `run_id`)
- `GET  /v1/connectors` · `GET /v1/connectors/{key}` — discover connectors + their tools/scopes
- `GET  /v1/credentials` · `POST /v1/credentials` · `DELETE /v1/credentials/{connector_key}` —
  per-tenant credential vault (secret is **write-only**; never returned)
- `GET  /v1/spend` — rated spend for the tenant (filter by `run_id`, `agent_id`, `since`)
- `GET  /v1/spend/agents` — cost per agent (the fleet spend breakdown)
- `GET  /v1/wallet` · `PATCH /v1/wallet` — wallet balance (a cached projection of the ledger), with
  `reserved`/`available`; PATCH toggles prepaid credit control (`enforce_balance`)
- `GET  /v1/rate-cards` — the tenant's rate cards (active pricing: per-model, per-tool/connector)
- `GET  /v1/budgets` · `POST /v1/budgets` · `DELETE /v1/budgets/{id}` — spend caps (soft/hard,
  tenant/agent scope); a hard cap stops an agent at the limit. Amounts are integer **nanodollars**
  (1 USD = 1e9) plus a `*_usd` display string; budgets are set in dollars (`limit_usd`).
- `GET  /v1/alerts` — spend/anomaly alerts (budget breaches, spend spikes, runaway loops,
  reconciliation drift)
- `POST /v1/billing/topups` · `POST /v1/billing/topups/{order_id}/confirm` — create a Razorpay
  top-up order and confirm it with the signed checkout callback (credits the prepaid wallet)
- `GET  /v1/billing/payments` · `POST /v1/billing/payments/{id}/refund` — list payments; refund
- `POST /v1/webhooks/razorpay` — Razorpay webhook (unauthenticated; HMAC-signature verified),
  reconciled into the ledger; idempotent with the checkout confirm
- `GET  /v1/billing/reconciliation` — ledger integrity + gateway drift (margin leak detection)
- `GET  /v1/invoices` · `POST /v1/invoices` · `GET /v1/invoices/{id}` — one itemized statement per
  tenant across the fleet, line items rolled from the ledger (`cost`, `price`, `margin`)
- `GET  /v1/ops/stream` — durable metering-stream health (log head, event count, consumer offset, lag)
- `POST /v1/ops/replay` — replay the tenant's usage stream through the idempotent pipeline; returns
  the exactly-once result (new ledger entries, balance delta) and repairs any captured-but-unrated gap
- `GET  /v1/ops/scheduler` — fair-scheduler capacity (global + per-tenant caps) and this tenant's share
- `GET  /v1/ops/providers` — model-router provider health (candidates, which circuits are open)
- `GET  /v1/auth/roles` — the RBAC role → permission matrix; `POST /v1/auth/sso/token` — mint a mock
  SSO token (dev only; `AGENTOS_SSO_MODE=mock`). Any endpoint accepts an API key **or** an SSO JWT.
- `GET|POST /v1/members` · `PATCH|DELETE /v1/members/{id}` — members + their RBAC roles
- `GET|POST /v1/api-keys` · `DELETE /v1/api-keys/{id}` — scoped API keys (plaintext shown once)
- `GET  /v1/audit` — the control-plane audit trail (who did what), exportable for a review
- `GET  /v1/compliance/report` — security-posture snapshot; `POST /v1/compliance/retention/purge`;
  `POST /v1/compliance/keys/rotate` — enforce retention / rotate the credential vault's master key
- `GET|POST /v1/admin/holds` · `POST /v1/admin/holds/scan` · `POST /v1/admin/holds/{id}/release` —
  fraud/abuse holds (a held tenant's billable work is refused with 403 `tenant_held`)
- `GET  /v1/marketplace` · `POST /v1/marketplace/publish/{agent,connector}` ·
  `POST /v1/marketplace/{id}/install` — share/install agent templates + connectors across tenants
- Phase 0 spike: `POST /v1/runs`, `POST /v1/runs/sync`, `WS /v1/runs/stream`

Write endpoints are gated by RBAC: the caller's role must grant the matching `<resource>:<action>`
permission (the `owner` role grants all). A velocity breach returns 429 `velocity_exceeded`; a
tenant on a fraud hold returns 403 `tenant_held`.

A run halted by a hard budget **or a depleted prepaid balance** finalizes with status `stopped`
(distinct from `completed`/`failed`). Money crosses the API as integer **nanodollars** (1 USD = 1e9)
plus a `*_usd` display string; amounts in are set in dollars (`amount_usd`, `limit_usd`).
