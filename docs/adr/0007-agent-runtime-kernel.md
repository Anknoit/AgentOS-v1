# ADR-0007: Agent runtime kernel — LangGraph with checkpointing

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 1

## Context

Phase 1 needs a real agent that runs **server-side as a managed job** — configured from a
versioned record, executed off the request path, fully logged, metered, and **resumable across a
worker restart** (the exit criterion). We must decide how the agent executes (the kernel), where
its execution state lives (so it can resume), and how that interacts with the exactly-once
metering invariant the whole product depends on.

The development plan names **LangGraph** for orchestration (stateful graphs, checkpointing,
human-in-the-loop) and **Arq** (ADR-0001) for the worker queue. The open questions were: use
LangGraph's own checkpointer or roll run state into our tables; and how to keep a resumed step
from double-counting usage.

## Decision

1. **Kernel = LangGraph `StateGraph`.** An agent run is a graph (`triage → retrieve → respond →
   finalize` for Support Desk). Nodes do the work, append to `action_log`, and push events to an
   `EventSink` the caller streams over WebSocket. The graph is compiled with a **checkpointer**,
   so state is persisted after every node.

2. **Checkpoint store is separate from the app DB, keyed by `thread_id = run_id`.**
   - SQLite dev-fallback → `AsyncSqliteSaver` on a **sibling file** (`<db>.ckpt`), so LangGraph's
     writer never contends for the application DB's file lock.
   - In-memory SQLite → `MemorySaver` (resume within the process only).
   - Postgres full stack → `AsyncPostgresSaver` (the durable cloud/worker path).

3. **The `run` row is the control record; the checkpoint is the execution state.** `run` carries
   status (`queued → running → paused → completed | failed | killed`), the pinned
   `agent_version_id`, the trace id, timings, and rolled-up result. `action_log` is the
   append-only per-step audit trail.

4. **Exactly-once is guaranteed by deterministic idempotency keys, not by the checkpoint.** Each
   billable step derives its key from `{run_id}:step{seq}:{kind}`, so a node that re-executes
   after a resume re-captures the *same* `usage_event` (a no-op) and re-appends the *same*
   `action_log` row (idempotent on `(run_id, seq)`). This is what makes it safe for the
   checkpoint to live in a separate store from the metering data.

5. **Managed execution, two backends.** In the dev-fallback an in-process `RunManager` drives the
   run in a background task and fans events out to subscribers — a client can disconnect and the
   run still completes. With Redis configured the **same kernel** runs on an Arq worker
   (`execute_agent_run_job`); on restart, unfinished runs are re-entered with `resume=True`.

## Options considered

- **Roll execution state into the `run` table ourselves (no LangGraph checkpointer).** One
  transaction for checkpoint + action_log + usage, so a crash can't desync them. Cost: we
  reimplement graph orchestration, step boundaries, and resume — exactly what LangGraph gives us
  — and diverge from the planned stack. Rejected: the desync risk is already neutralized by
  deterministic idempotency keys (decision 4), so co-location buys little.
- **LangGraph checkpointer in the same SQLite file as the app DB.** One file, simpler ops. Cost:
  two async writers on one SQLite file contend for the write lock under concurrent runs.
  Rejected for the sibling-file split.
- **Temporal instead of Arq + LangGraph.** Stronger durability guarantees out of the box. Cost:
  heavy operational surface for v0; ADR-0001 already deferred it. Revisit if long-running
  durability demands it.

## Consequences

- Resume is demonstrable offline on the SQLite fallback: a run whose model step crashes mid-way
  leaves its checkpoint intact and resumes to completion — with the already-metered tool step
  **not** re-counted (covered by `tests/test_run_resume.py`).
- The checkpoint store is **not** the billing source of truth and need not be backed up with the
  same rigor as `usage_event` / the ledger; losing a checkpoint costs a re-run, not money.
- Two checkpointer backends (SQLite, Postgres) must track LangGraph's checkpoint schema; the
  Postgres saver is the production path and is exercised in the compose/CI profile, mirroring the
  RLS situation in ADR-0006.
- Guardrails (`max_steps`, `max_output_tokens`) are stored on `agent_version` now and enforced by
  the kernel as the graph grows beyond the linear Support Desk flow.
