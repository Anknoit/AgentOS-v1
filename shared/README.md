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

## Current surface (Phases 0–2)

- `GET  /health` — liveness + which DB/runtime profile is active (unauthenticated)
- `GET  /metrics` — Prometheus metrics (unauthenticated)
- `GET  /v1/whoami` — authenticated tenant context
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
- Phase 0 spike: `POST /v1/runs`, `POST /v1/runs/sync`, `WS /v1/runs/stream`
