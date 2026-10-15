<img src = "agentOs.png">
<br>

# AgentOS — The Control Plane for Your AI Agent Workforce

> **AgentOS is payroll and mission-control for AI agents.**
> One place to deploy agents, connect them to the tools you already run, and pay
> for everything they do on a single metered balance — with real-time cost control
> and a full audit trail on every action.

---

## What AgentOS Is

AgentOS is a **control plane for a company's AI agent workforce**. Teams use it to:

- **Deploy** role-based agents — Support Desk, Receptionist, Social Media, HR — from templates.
- **Connect** those agents to existing systems (Slack, CRM, email, calendar, voice, or any MCP/HTTP tool) with scoped, per-tenant credentials.
- **Pay** for all of them on one prepaid balance, metered per unit of work and settled into a single invoice.

The value — agents running 24/7, every billable action metered, spend settled — only
exists if the core runs **always-on and server-side**. So AgentOS is built
**backend-first**: a FastAPI service owns the runtime, metering, and settlement, and the
desktop app is a thin client onto it.

> AgentOS is **not** a chatbot and not a demo. It is the infrastructure that makes an
> agent fleet observable, governable, and billable in production.

---

## The Problem

Running one agent is easy. Running a **fleet** is not:

- Every agent burns tokens and calls paid tools — but spend is scattered across provider dashboards.
- Credentials and permissions sprawl, with no single place to scope or audit them.
- Nothing stops a runaway loop before it drains a budget.
- There is no single bill, no single balance, no single point of control.

AgentOS answers one question for the whole fleet:

> **"What is every agent doing, what is it costing, and can we stop it before it overspends?"**

---

## Core Design Principles

These tenets hold in every phase; the roadmap is how they get built in.

- **Backend-first, one backend, two modes.** The same FastAPI codebase runs as a local sidecar the desktop app spawns (dev and single-tenant) *and* as the multi-tenant cloud service. The client points at a configurable backend URL and never assumes which it is talking to.
- **Control plane vs. data plane.** Managing agents and reading state is separate from agents doing work; a flood of agent runs never takes down the management console.
- **Agents run as managed jobs, not request threads.** Work is enqueued and executed by stateless workers, so an agent survives a client disconnect, a deploy, or a crash.
- **Event-driven metering, decoupled from execution.** Every billable action emits a usage event onto a bus; rating and ledger writes happen downstream, off the hot path.
- **Exactly-once accounting.** Every usage event carries an idempotency key; a retried model call or replayed event must never double-bill.
- **Append-only ledger; balances are projections.** Money movements are immutable entries; a wallet balance is a derived, cached view — auditable by construction.
- **Real-time credit control.** Before a billable action, the runtime checks the wallet against budgets and balance and can throttle or stop — the telecom online-charging pattern, not after-the-fact reporting.
- **Tenant isolation everywhere.** `tenant_id` is on every row, event, and log line, enforced at the data layer. Credentials are encrypted per tenant.
- **Config is data, and versioned.** An agent definition is a versioned record; a run pins the exact version it executed, so changes are diffable and rollback-able.
- **Stable, versioned API contract.** The client and the separately-built UI depend only on a versioned REST + WebSocket surface with a generated typed SDK.
- **Observability is not optional.** Structured logs, metrics, and traces from day one — one trace id spanning client → API → worker → provider.

---

## Architecture Overview

The desktop client talks **only** to the FastAPI gateway. Every core service — the
runtime, connectors, and the charging core — lives behind it, server-side, and runs
whether or not the desktop app is open.

```
            ┌───────────────────────┐
            │   Electron Desktop     │   thin client · configurable backend URL
            │        Client          │
            └───────────┬───────────┘
                        │  REST + WebSocket (versioned, typed SDK)
            ┌───────────▼───────────┐
            │     FastAPI Gateway    │
            └───────────┬───────────┘
      ┌─────────────────┼─────────────────────────────┐
      ▼                 ▼                             ▼
┌───────────┐   ┌───────────────┐          ┌────────────────────┐
│  Agent    │   │  Connector    │          │   Charging Core     │
│  Runtime  │──▶│  Framework    │          │  metering · rating  │
│ (workers) │   │  (MCP/OAuth)  │          │  wallet · ledger    │
└─────┬─────┘   └───────────────┘          └─────────▲──────────┘
      │  usage_event (per billable action)           │
      └──────────────── event bus ───────────────────┘
                     (real-time credit control: check wallet before each action)
```

**The charging loop is the distinctive part:** the runtime emits a usage event for
every billable action → metering rates it against the rate card → the wallet is
debited — and the runtime checks the wallet's balance and budget *before* each action.

---

## Core Data Model

Every row carries `tenant_id`. The highlighted entities are the heart of the moat —
their shape is fixed before breadth is built.

| Entity | What it holds |
|---|---|
| `tenant` | Organization account — root of isolation and billing |
| `user` | People in a tenant, with roles for RBAC |
| `agent` | A logical agent ("employee") — name, role, status, current version |
| `agent_version` | Versioned, immutable config: model, tools, guardrails, knowledge, connector bindings |
| `run` | One execution of an agent — pins its `agent_version`, status, trace id |
| `action_log` | Every step and tool call in a run — append-only audit trail |
| **`usage_event`** | **One billable unit of work — provider, model, quantity, run, idempotency key** |
| **`rate_card`** | **Pricing — per-model token prices, per-tool fees, platform fee, effective dates** |
| **`ledger_entry`** | **An immutable money movement — refs a usage event, top-up, or invoice** |
| `wallet` | Tenant balance — cached running total, currency, budgets attached |
| `budget` | A cap or limit — scope, period, hard/soft, action on breach |
| `connector` | An integration instance — type and granted scopes |
| `credential` | Encrypted per-tenant secret for a connector |
| `invoice` | A billing statement — line items rolled from the ledger |

---

## Tech Stack

Boring, proven components by default; the only exotic choices are where the charging
core or scale demands them.

| Layer | Choice | Why |
|---|---|---|
| Desktop shell | **Electron** + secure IPC | Cross-platform management console; web UI fits building UI with AI |
| API backend | **FastAPI** (async, Pydantic) | Typed, async, OpenAPI for free — generates the client/UI SDK |
| Agent orchestration | **LangGraph** | Stateful graphs, checkpointing, human-in-the-loop |
| Execution / workers | **Temporal** (recommended) | Durable, resumable long-running workflows; Celery/Arq a lighter v0 |
| Primary database | **Postgres** | Config, ledger, tenancy in one store; row-level security for isolation |
| Cache + credit control | **Redis** | Real-time balance/budget checks, rate limits, locks on the hot path |
| Event bus | **NATS → Kafka** | Usage-event transport; Kafka for durable, replayable metering at scale |
| Usage store | **ClickHouse** | High-volume usage events and spend analytics (Timescale a Postgres-native alternative) |
| Credential vault | **Postgres + envelope encryption (KMS)** | Per-tenant secrets encrypted at rest |
| Payments | **Stripe** (Billing + Connect) | Top-ups, invoicing, payouts — don't build a payment rail |
| Connector protocol | **MCP** | Reuse the growing tool-integration ecosystem |
| Auth & identity | **OIDC** (Clerk / Auth0) | Tenants, users, API keys now; SSO/SAML later |
| Observability | **OpenTelemetry + Prometheus/Grafana** | One trace id from client → API → worker → provider |
| Packaging | **electron-builder + FastAPI sidecar (PyInstaller)** | Ships client and local backend together; auto-update |

---

## Roadmap

Phased to de-risk the metering/settlement moat while shipping a working agent early.
Phases are ordered, not dated.

| Phase | Goal |
|---|---|
| **0 — Foundations** | Monorepo, Electron ↔ backend contract, auth + multi-tenancy skeleton, observability baseline, de-risk spikes |
| **1 — Agent runtime MVP** | One real agent end to end — configured, run server-side, fully logged, metering captured (not yet billed) |
| **2 — Connector framework** | Scoped capabilities, connector SDK + registry (MCP), credential vault, 2–3 real connectors |
| **3 — Metering, rating & budgets** | Accurate per-agent cost and real-time budgets on your own keys — **the start of the moat** |
| **4 — Settlement & payments** | Prepaid wallet, Stripe, provider pass-through + markup, one invoice, reconciliation — **the payment path** |
| **5 — Scale & reliability** | Horizontal workers, Kafka exactly-once ingestion, multi-provider routing, voice, HA/DR |
| **6 — Enterprise & hardening** | SOC 2, RBAC + SSO/SAML, fraud controls, agent/connector marketplace, self-hosted packaging |

**Sequencing principle:** ship a usable, connected agent by Phase 2 and the defensible
core (rating, budgets, settlement) by Phase 4 — with metering instrumented from Phase 1,
built on real usage rather than polishing breadth before the moat exists.

---

## Starter Agent Templates

AgentOS ships with four role templates, deployable from a gallery and tuned in a focused editor:

- **Support Desk** — answers customer questions and resolves tickets · Helpdesk, Slack, KB
- **Receptionist** — greets, routes, and books across voice and chat · Telephony, Calendar
- **Social Media** — drafts, schedules, and replies across channels · X, LinkedIn, Buffer
- **HR Agent** — handles onboarding, policy Q&A, and leave requests · HRIS, Email, Docs

Each agent is configured through Identity, Behavior, Knowledge, Tools & Connectors,
Guardrails, Schedule, and Budget — with a live test console and a running cost estimate.

---

## Repository Layout

- `AgentOS — Development Plan.docx` — the backend-first, phased engineering plan (the source of truth).
- `BUILD_PLAN.md` — the sequential, executable build plan derived from the development plan.
- `AgentOS-UI-Prompt.md` — a build-ready specification for the product UI (design system and every core screen).
- `backend/` — the FastAPI service (runtime, metering, settlement). Runs as the Electron sidecar **and** the cloud service. See [backend/README.md](backend/README.md).
- `desktop/` — the Electron shell: spawns + supervises the backend sidecar, secure IPC, auto-update. See [desktop/README.md](desktop/README.md).
- `shared/` — the versioned API contract (OpenAPI) + generated client SDK. See [shared/README.md](shared/README.md).
- `AgentOS_ui/` — the web UI (TanStack Start), a thin client over the versioned API.
- `infra/` — docker-compose dev stack (Postgres, Redis, NATS; optional observability).
- `docs/adr/` — Architecture Decision Records for the locked Phase 0 choices.

### Local development (Phase 0)

```bash
# backend — zero external services (SQLite dev-fallback, mock LLM)
cd backend && uv venv && uv pip install -e ".[dev]"
uv run pytest                 # run the test suite
uv run agentos serve          # http://127.0.0.1:8787  (/v1/docs for Swagger)

# desktop — spawn + supervise the backend sidecar end to end (headless)
cd desktop && npm install && npm run smoke:sidecar

# full Postgres + RLS stack (requires Docker)
docker compose -f infra/docker-compose.yml up -d
cd backend && AGENTOS_DATABASE_URL=postgresql+asyncpg://agentos:agentos@localhost:5432/agentos \
  uv run alembic upgrade head
```

---

## What Makes AgentOS Different

| Typical agent tooling | AgentOS |
|---|---|
| Spend scattered across provider dashboards | One metered balance, one invoice |
| Report cost after the fact | Real-time credit control — stop before overspend |
| Credentials sprawl | Scoped, per-tenant, encrypted connectors |
| Black-box runs | Append-only action log + usage ledger per run |
| Single-agent demos | A control plane for the whole fleet |

---

## One-Line Summary

> **AgentOS is the control plane for an AI agent workforce — deploy agents, connect them
> to your tools, and pay for everything they do on one metered, settled balance, with
> real-time cost control and a full audit trail.**

---

## License

MIT (for now)
