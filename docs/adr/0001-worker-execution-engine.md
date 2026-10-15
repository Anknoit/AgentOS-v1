# ADR-0001: Worker / execution engine — Arq (Redis) for v0

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 0

## Context

Agent runs must execute **off the request path** as managed jobs: they have to survive a
client disconnect, a deploy, and a worker restart (core principle: "agents run as managed
jobs, not request threads"). We need a job queue + stateless workers chosen in Phase 0,
because the plan flags this as **expensive to swap after Phase 1** — the runtime kernel,
checkpointing, and metering hooks all bind to the engine's execution model.

The development plan recommends **Temporal** for durable, resumable long-running workflows,
and names **Celery/Arq** as a lighter v0.

## Decision

Use **Arq** (async Redis-backed task queue) as the v0 execution engine. Redis is already in
the stack for credit control and caching, so Arq adds no new infrastructure. Keep the runtime
kernel's coupling to the engine behind a thin `runtime/queue` interface so a later swap to
Temporal is contained.

## Options considered

- **Temporal** — durable, resumable workflows with built-in retries, timers, and history
  replay; the strongest fit for long-running agents. Cost: a Temporal server + workers to
  operate, a new programming model, and heavier local dev. Overkill before we have real
  long-running agents.
- **Celery** — mature, broad broker support. Cost: sync-first, heavier config, awkward with
  an async FastAPI codebase.
- **Arq** — async-native (fits FastAPI/asyncio), minimal, Redis-backed, trivial local dev.
  Cost: fewer durability guarantees than Temporal (no built-in workflow history / replay);
  we build checkpointing in the runtime kernel (Phase 1) rather than getting it from the
  engine.

## Consequences

- Fast to stand up; no new infra beyond Redis.
- Durable workflow semantics (resume-after-crash mid-step) are **our responsibility** —
  delivered via LangGraph checkpointing + idempotent run steps in Phase 1, not by the engine.
- **Reversal cost:** swapping to Temporal after Phase 1 means rewriting the run-execution glue
  and re-homing checkpointing. Contained to `runtime/queue.py` + the worker entrypoint by
  design, but still a deliberate migration. Decide before Phase 1 ships if long-running
  durability demands it.
