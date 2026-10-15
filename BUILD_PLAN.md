# AgentOS — Phase-wise Build Plan

A sequential, executable build plan derived from **AgentOS — Development Plan.docx**.
Each phase below is a self-contained unit of work: run them **in order, one after the other**.
A phase is "done" only when its **Exit criteria** pass — do not start the next phase until they do.

> **How to use this file**
> 1. Read **Conventions & locked decisions** once. Settle anything marked _DECIDE_ before Phase 0.
> 2. For each phase, work through **Build tasks** top to bottom.
> 3. Verify against **Exit criteria** (these mirror the development plan's exit gates).
> 4. Commit at the end of each phase with the tag shown under **Milestone commit**.
> 5. The web UI lives in `AgentOS_ui/` and is built separately — see **UI integration** at the end. The contract between them is the versioned REST + WebSocket API.

---

## Context snapshot

- **Product:** control plane for an AI agent workforce — agents running 24/7, metering every unit of work, settling spend.
- **Architecture:** backend-first. One FastAPI codebase runs in **two modes**: (a) a local sidecar that Electron spawns (dev / single-tenant / self-hosted), and (b) the cloud multi-tenant service. The client points at a configurable backend URL and never assumes which it talks to.
- **The moat:** event-driven metering → rating → append-only ledger → real-time credit control (the telecom online-charging pattern). Protect accounting accuracy, idempotency, and tenant isolation above everything else.
- **In scope here:** FastAPI backend + all core services; Electron shell (process model, sidecar lifecycle, secure IPC, packaging, auto-update, typed API client); data model and system design.
- **Out of scope here:** UI screens/components (built separately in `AgentOS_ui/`). They depend only on the versioned REST + WebSocket API + generated SDK.

---

## Target monorepo layout

Build toward this structure (created in Phase 0, filled in later phases):

```
AgentOS-v1/
├── backend/                 # FastAPI service (runs as sidecar AND cloud)
│   ├── app/
│   │   ├── main.py          # app factory, router mounting, middleware
│   │   ├── config/          # settings (pydantic-settings), env
│   │   ├── core/            # cross-cutting: auth, tenancy, otel, logging, errors
│   │   ├── db/              # engine, session, migrations (alembic), RLS setup
│   │   ├── models/          # SQLAlchemy models (the data model below)
│   │   ├── schemas/         # Pydantic request/response DTOs
│   │   ├── api/             # versioned routers: /v1/...
│   │   ├── runtime/         # agent kernel, LangGraph graphs, workers, queue
│   │   ├── connectors/      # capability abstraction, SDK, registry, vault
│   │   ├── metering/        # usage pipeline, rating engine, ledger, budgets
│   │   ├── billing/         # wallet, Stripe, invoicing, reconciliation
│   │   └── ws/              # WebSocket run-event streaming
│   └── tests/
├── desktop/                 # Electron shell (client over the backend)
│   ├── src/main/            # main process: sidecar lifecycle, backend URL, auto-update
│   ├── src/preload/         # secure IPC bridge (contextIsolation on)
│   └── electron-builder.yml
├── shared/                  # generated OpenAPI client SDK + shared types
├── AgentOS_ui/              # (existing) web UI — consumes shared SDK
├── infra/                   # docker-compose for dev (postgres, redis, bus, usage store)
├── docs/adr/                # Architecture Decision Records
└── BUILD_PLAN.md            # this file
```

---

## Conventions & locked decisions

Lock these before Phase 0 (record each as an ADR in `docs/adr/`). Where the plan recommends a heavy component, a **pragmatic v0** is offered so each phase is runnable by a small team; the moat design is preserved either way.

| Concern | Plan's choice | Pragmatic v0 (recommended to start) | Decide |
|---|---|---|---|
| Desktop shell | Electron + secure IPC | same | — |
| API backend | FastAPI (async, Pydantic) | same | — |
| Agent orchestration | LangGraph | same | — |
| Execution / workers | Temporal | **Arq** (Redis-backed) in v0; swap to Temporal if long-running durability demands it (expensive to swap after Phase 1 — _DECIDE in Phase 0_) | ADR-01 |
| Primary DB | Postgres (+ row-level security) | same | — |
| Cache + credit control | Redis | same | — |
| Event bus | NATS → Kafka | **NATS** in v0; Kafka in Phase 5 | ADR-02 |
| Usage store | ClickHouse / Timescale | **Postgres table** in v0 (Phase 3); move to ClickHouse/Timescale when volume demands (Phase 5) | ADR-03 |
| Credential vault | Postgres + envelope encryption (KMS) | Postgres + envelope encryption (local KMS/age key in dev) | — |
| Payments | Stripe (Billing + Connect) | Stripe test mode | — |
| Connector protocol | MCP | MCP + generic HTTP escape hatch | — |
| Auth & identity | OIDC (Clerk/Auth0) | API keys + simple tenant/user tables in v0; OIDC in Phase 6 | ADR-04 |
| Observability | OpenTelemetry + Prometheus/Grafana | OTel from day one; Prometheus/Grafana via docker-compose | — |
| Packaging | electron-builder + PyInstaller sidecar | same | — |
| Settlement vs BYO-keys for first revenue | BYO in Phase 3, settlement in Phase 4 | same | ADR-05 |

**Non-negotiable invariants (every phase must honor these):**
- `tenant_id` on every row, event, and log line; enforced at the data layer (Postgres RLS), not just app code.
- Every `usage_event` carries an **idempotency key**; rating and ledger writes dedupe on it (exactly-once accounting).
- Ledger is **append-only**; balances are projections (with a cached running total).
- Real-time credit control: check wallet balance + budget **before** each billable action.
- Config is versioned data: a `run` pins the exact `agent_version` it executed.
- One trace id spans client → API → worker → provider call.

---

## Core data model (build incrementally across phases)

Every row carries `tenant_id`. `usage_event`, `rate_card`, and `ledger_entry` are the heart of the moat — fix their shape before building breadth.

| Entity | Holds | Introduced in |
|---|---|---|
| `tenant` | Organization account; root of isolation + billing | Phase 0 |
| `user` | People in a tenant; roles for RBAC | Phase 0 (roles expanded Phase 6) |
| `agent` | A logical agent ("employee"); name, role, status, current version ref | Phase 1 |
| `agent_version` | Immutable versioned config: model, tools, guardrails, knowledge refs, connector bindings | Phase 1 |
| `run` | One execution; pins `agent_version`; status, start/end, trace id | Phase 1 |
| `action_log` | Append-only audit trail of every step/tool/model call | Phase 1 |
| `usage_event` | One billable unit: provider, model, tokens/qty, agent_id, run_id, idempotency key | Phase 1 |
| `connector` | Integration instance; type (Slack, CRM, MCP), granted scopes | Phase 2 |
| `credential` | Encrypted secret for a connector; per tenant | Phase 2 |
| `rate_card` | Per-model token prices, per-tool fees, platform fee; effective dates; cost vs price | Phase 3 |
| `ledger_entry` | Immutable money movement; refs a usage_event / top-up / invoice | Phase 3 |
| `wallet` | Cached tenant balance + currency; budgets attached | Phase 3 |
| `budget` | Cap/limit: scope (tenant/agent), period, hard/soft, action on breach | Phase 3 |
| `invoice` | Billing statement; period, line items rolled from the ledger, status | Phase 4 |

---

## Phase 0 — Foundations

**Goal:** a thin skeleton that proves the hardest unknowns and lays the rails everything rides on. Keep it thin — spikes retire risk, they are not production code.

### Build tasks
1. **Monorepo + tooling.** Create `backend/`, `desktop/`, `shared/`, `infra/`, `docs/adr/`. Set up linting (ruff/black for Python, eslint/prettier for TS), a test harness (pytest + vitest), and `infra/docker-compose.yml` with Postgres and Redis.
2. **ADRs.** Write `docs/adr/` records for ADR-01…ADR-05 above (worker engine, event bus, usage store, auth, settlement-vs-BYO). Decide the worker engine now — it is expensive to swap after Phase 1.
3. **FastAPI skeleton.** App factory in `backend/app/main.py`, settings via `pydantic-settings`, health endpoint, `/v1` router mount, versioned OpenAPI enabled.
4. **Electron ↔ backend contract.** Electron main process reads a **configurable backend URL**; in local mode it **spawns and supervises the FastAPI sidecar**; secure IPC with `contextIsolation: true` and no node integration in the renderer; stub auto-update wiring.
5. **Auth & multi-tenancy skeleton.** `tenant`, `user`, API-key tables; `tenant_id` threaded through every request (middleware/dependency); **Postgres row-level security switched on in the first migration**.
6. **Observability baseline.** Structured logging, OpenTelemetry tracing, and metrics wired **before features** — one trace id generated at the client and propagated through API → worker.
7. **De-risk spikes:** (a) run one LLM agent loop; (b) stream tokens to the client over WebSocket; (c) capture token usage from a provider response and write exactly one `usage_event`.

### Exit criteria
A developer launches the Electron app → it starts the local FastAPI sidecar → authenticates as a tenant → triggers a trivial agent loop → sees streamed output, **with a trace spanning client → API → worker**.

### Milestone commit
`phase-0: foundations — monorepo, sidecar lifecycle, RLS, otel, agent-loop spike`

---

## Phase 1 — Agent runtime MVP

**Goal:** one real agent end to end — configured, run server-side, fully logged, with metering **captured (not yet billed)**.

### Build tasks
1. **Config schema:** `agent` + `agent_version` models/schemas — role, model, system prompt, tools, guardrails, knowledge refs. **Versioned and validated**; `agent_version` is immutable.
2. **Runtime kernel** (`backend/app/runtime/`): agent lifecycle `create → start → pause → stop → kill`; state/memory persistence; execution as a **LangGraph graph with checkpointing**.
3. **Job queue + stateless workers** (chosen engine): runs are **enqueued and executed off the request path**; survive client disconnect, deploy, and worker restart.
4. **Action logging:** append every step, tool call, and model call to `action_log` with the trace id.
5. **Metering hooks from day one:** emit a `usage_event` per model and tool call with an **idempotency key**, written to a store — **not yet rated**.
6. **One template end to end:** build **Support Desk** — config → run → streamed output → complete audit log.
7. **Backend API surface for clients** (`/v1`): agents CRUD, trigger run, **stream run events over WebSocket**, read logs.

### Exit criteria
Create a Support Desk agent from config, run it against a sample task, watch it stream, inspect a complete `action_log` and the `usage_event`s it generated — all server-side, **resumable across a worker restart**.

### Milestone commit
`phase-1: agent runtime MVP — LangGraph kernel, durable runs, action log, metering hooks`

---

## Phase 2 — Connector framework

**Goal:** agents that safely touch real systems, with permissions and credentials as first-class, scoped objects.

### Build tasks
1. **Capability abstraction:** typed interfaces for **messaging, data, and web** (voice deferred to Phase 5). Agents declare needed capabilities; the runtime grants only those.
2. **Connector SDK + registry:** a uniform way to define, register, and discover connectors, with **MCP as the primary protocol**.
3. **Credential vault** (`credential` model): OAuth and API-key flows; secrets **encrypted per tenant**; short-lived tokens where possible.
4. **Permission scoping enforced by the runtime:** an agent can reach only the connectors/scopes its `agent_version` grants — **checked at call time, logged on every use**.
5. **Two or three real connectors** (e.g. Slack, a CRM/HTTP, email) **plus a generic MCP/HTTP connector** as the escape hatch.
6. **Threat-model this phase specifically** — credential handling and scope enforcement are where a breach would be worst. Keep every connector call attributable in the audit log.

### Exit criteria
A Support Desk agent reads from and posts to Slack and a CRM using **scoped, tenant-isolated credentials**; an attempt to use an **ungranted scope is denied and logged**.

### Milestone commit
`phase-2: connector framework — MCP registry, per-tenant vault, scope enforcement`

---

## Phase 3 — Metering, rating & budgets

**Goal:** accurate per-agent cost and real-time budgets, **on your own keys**, before taking on payments. **This is the start of the moat.**

### Build tasks
1. **Metering pipeline:** consume `usage_event`s off the bus, normalize + enrich (provider, model, tokens, tool, agent, run, tenant), land them in the **usage store**.
2. **Rating engine:** price each event against the active `rate_card` (per-model token prices, per-tool fees, platform fee), **versioned with effective dates** — the telecom rating pattern.
3. **Cost ledger:** append-only `ledger_entry` per rated event, attributed to agent + tenant; **wallet balance as a cached projection**.
4. **Real-time budgets and caps** (`budget`): balance + budget checked **before each billable action**; soft caps alert, hard caps throttle/stop the agent (online credit control).
5. **Spend APIs for the client:** cost per agent / per run / per period — the data behind the unified spend view.
6. **Alerts + simple anomaly detection** on spend spikes and runaway loops.
7. **Lock in idempotency and exactly-once rating here** — every later phase trusts these numbers.

### Exit criteria
Run several agents and see accurate, per-agent **rated spend within a small error** of the providers' own numbers; set a **hard cap** and watch an agent **stop at the limit**.

### Milestone commit
`phase-3: metering, rating & budgets — usage pipeline, rate card, append-only ledger, credit control`

---

## Phase 4 — Settlement & payments

**Goal:** enter the payment path — **one balance in, one invoice out, across every agent**. This is where "single point to pay your agents" becomes real and where the margin is.

### Build tasks
1. **Prepaid wallet:** load a balance, **reserve/hold against in-flight work**, debit on rated usage — all through the append-only ledger.
2. **Stripe integration:** top-ups, saved payment methods, invoicing; **webhooks reconciled into the ledger**.
3. **Provider pass-through + markup:** `rate_card` carries **cost** (provider charge) and **price** (tenant pays); margin is an accounted ledger quantity, not a guess.
4. **Invoicing engine** (`invoice`): one statement per tenant across all agents, line items rolled from the ledger; usage-based and/or platform-fee billing.
5. **Reconciliation:** compare metered/rated spend against providers' actual invoices; **surface drift** so margin never silently leaks.
6. **Test the money edge cases** before any paying tenant: refunds, failed top-ups, disputes, double-spend, race on concurrent debits.

### Exit criteria
A tenant tops up once, runs a mixed fleet, and receives a **single itemized invoice** whose totals reconcile against provider bills within tolerance; a **depleted balance stops further billable work**.

### Milestone commit
`phase-4: settlement & payments — prepaid wallet, Stripe, invoicing, reconciliation`

---

## Phase 5 — Scale & reliability

**Goal:** hold accuracy and uptime as agents, tenants, and event volume grow by orders of magnitude.

### Build tasks
1. **Horizontal worker scaling:** partition the run queue **per tenant**; add backpressure and fair scheduling so one noisy tenant can't starve others.
2. **High-throughput metering ingestion:** move the event bus to **Kafka**; stream-process usage events with **exactly-once semantics**.
3. **Multi-provider routing + failover:** provider-agnostic rate card and a model router with **cost-aware selection** and failover when a provider degrades.
4. **Caching + idempotency hardening** across rating and ledger writes; **replay tooling** for the event stream.
5. **Voice/telephony capability subsystem** (low-latency) for the Receptionist — add once demand justifies the infra.
6. **HA + DR:** read replicas, usage-store sharding, backups, **tested restore**, defined RPO/RTO.

### Exit criteria
A load test at target scale sustains **correct, exactly-once metering** and within-SLA run latency; **killing a worker or failing a provider causes no lost or double-counted usage** (prove with chaos + replay testing).

### Milestone commit
`phase-5: scale & reliability — Kafka ingestion, per-tenant queues, failover, HA/DR`

---

## Phase 6 — Enterprise & hardening

**Goal:** clear the trust and expansion bars a product handling money, credentials, and a whole agent fleet must meet. Sequence against **real demand** so these don't starve the core.

### Build tasks
1. **Compliance path:** SOC 2 controls, full audit logging, data-retention + residency policies, encryption and **key rotation**.
2. **RBAC + SSO/SAML:** granular roles over agents, spend, and connectors; enterprise identity (graduate the Phase 0 auth skeleton to OIDC).
3. **Fraud and abuse controls:** velocity limits, anomaly-driven holds, prepaid-abuse protection.
4. **Marketplace:** share/install agent templates and connectors across tenants (network-effect lever).
5. **Self-hosted / on-prem packaging:** mature the local FastAPI mode into a **supported single-tenant deployment** (their server, not a laptop — 24/7 agents on a desktop is not viable).

### Exit criteria
An enterprise tenant onboards with **SSO and scoped roles**, passes a security review, and runs on **isolated or self-hosted infrastructure** with full audit export.

### Milestone commit
`phase-6: enterprise & hardening — SOC2 controls, RBAC/SSO, fraud controls, marketplace, self-hosted`

---

## Phase roadmap & sequencing

```
Phase 0 ──▶ Phase 1 ──▶ Phase 2 ──▶ Phase 3 ──▶ Phase 4 ──▶ Phase 5 ──▶ Phase 6
foundations  runtime     connectors  metering    settlement  scale        enterprise
             MVP                     & budgets    & payments  & reliability & hardening
   │           │            │            │            │
   └─ rails    └─ working, connected ────┘   moat     └─ payment-path gate
                  agent by Phase 2         by Phase 4
```

- **Phases 0–2:** stand up a working, connected agent.
- **Phase 3:** metering + control on your own keys — the moat starts.
- **Phase 4:** cross the gate into the payment path (the margin).
- **Phases 5–6:** scale and harden.
- Metering is instrumented from **Phase 1**. Phases are ordered, not dated — attach calendar dates once team size is known.

---

## Cross-cutting risks & key decisions (settle as ADRs in Phase 0)

- **Settlement vs BYO-keys for first paying users** — ship BYO (Phase 3) for revenue before full settlement (Phase 4). Decide how long you stay BYO before entering the payment path. _(ADR-05)_
- **Execution engine: Temporal vs a lighter queue** — Temporal buys durable, resumable workflows at operational cost; Celery/Arq is faster to stand up. **Pick in Phase 0; expensive to swap after Phase 1.** _(ADR-01)_
- **Usage store: ClickHouse vs Timescale (vs Postgres v0)** — ClickHouse scales analytics further; Timescale stays in the Postgres world. Expected metering volume decides it. _(ADR-03)_
- **Build vs orchestrate the agents** — building the native runtime owns the whole stack and margin; sitting on top of existing agents is faster to the wedge with less control. A hybrid is viable.
- **Desktop-first vs web-first client** — keep the UI a **thin client over the versioned API** so a web build is cheap later.
- **Where agents execute in self-hosted mode** — self-hosted means **their server, not their desktop**. Keep that boundary explicit.

**Through-line:** protect the metering/settlement core. Every decision touching accounting accuracy, idempotency, or tenant isolation is load-bearing; most other choices are reversible.

---

## UI integration (parallel track)

The web UI in `AgentOS_ui/` (TanStack Start, already scaffolded with mock state) is built **separately** and consumes the backend only through the **versioned REST + WebSocket API + generated SDK** in `shared/`.

- After **Phase 1**, generate the typed client SDK from the backend's OpenAPI into `shared/` and begin replacing `AgentOS_ui/src/lib/agentos/mockData.ts` / `store.tsx` with real API calls.
- UI roadmap (`AgentOS_ui/roadmap.md`) maps roughly onto backend phases: dashboard/fleet + agent config/test console → Phase 1; connectors + scoped auth → Phase 2; live billing/budgets/usage export → Phase 3; add funds / checkout → Phase 4; onboarding + workspace settings → Phase 6.
- Keep the API contract stable and versioned so UI and backend progress in parallel.

---

_Generated from AgentOS — Development Plan.docx. Keep this file in sync when ADR decisions change the locked choices above._
