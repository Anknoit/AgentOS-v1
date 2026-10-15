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

## Typed client SDK (fills in after Phase 1)

Per the build plan, once the Phase 1 API surface is real we generate a typed TS client here and
begin replacing `AgentOS_ui/src/lib/agentos/mockData.ts` + `store.tsx` with real calls. Planned:

```bash
npx openapi-typescript shared/openapi.json -o shared/src/api-types.ts
```

plus a thin fetch/WebSocket wrapper that injects `Authorization` and the `X-Trace-Id` header
(so a trace starts on the client and spans client → API → worker).

## WebSocket contract (not in OpenAPI)

`WS /v1/runs/stream` — connect with `?token=<api-key>` (or an `Authorization: Bearer` header),
send `{"task": "..."}`, and receive a stream of run-event frames:

| `type`        | fields |
|---------------|--------|
| `run_started` | `run_id`, `provider` |
| `token`       | `run_id`, `text` |
| `usage`       | `run_id`, `usage_event_id`, `input_tokens`, `output_tokens`, `total_tokens` |
| `done`        | `run_id`, `usage_event_id` |
| `error`       | `run_id`/none, `message` |

## Current Phase 0 surface

- `GET /health` — liveness + which DB/runtime profile is active (unauthenticated)
- `GET /metrics` — Prometheus metrics (unauthenticated)
- `GET /v1/whoami` — authenticated tenant context
- `POST /v1/runs` — trigger a run (in-process or enqueued to a worker)
- `POST /v1/runs/sync` — run and return the full result (non-streaming convenience)
- `GET /v1/usage` — list captured usage events
- `WS /v1/runs/stream` — stream run events
