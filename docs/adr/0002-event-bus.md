# ADR-0002: Event bus — NATS for v0

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 0

## Context

Metering is **event-driven and decoupled from execution**: every billable action emits a
`usage_event` onto a bus; rating and ledger writes happen downstream so metering never sits on
the agent's hot path. We need a transport chosen now so the metering pipeline (Phase 3) and
scale work (Phase 5) have a stable seam. The plan's path is **NATS → Kafka**: NATS early,
Kafka for durable, high-throughput, replayable metering at scale.

## Decision

Use **NATS** as the v0 event bus, behind a small `metering/bus.py` publisher/subscriber
interface. In Phase 0 the interface ships with an **in-process async implementation** (no
broker required to boot); NATS is wired via docker-compose and selected by config. Kafka
replaces NATS in Phase 5 behind the same interface.

## Options considered

- **NATS** — lightweight, simple ops, great for early decoupling. Core NATS is at-most-once;
  JetStream adds persistence/replay when needed. Good enough until volume demands Kafka.
- **Kafka** — durable, replayable, high-throughput, exactly-once with the right config; the
  Phase 5 target. Cost: heavy to operate; premature now.
- **Redis Streams** — already have Redis; tempting to avoid a component. Rejected to keep the
  metering transport independent of the credit-control/cache Redis and to keep a clean path to
  Kafka.

## Consequences

- The bus is an interface, not a hard dependency: the app boots with an in-process bus for dev
  and tests; NATS is opt-in via config.
- **Reversal cost:** low. Swapping NATS→Kafka is confined to `metering/bus.py` and consumer
  wiring, provided publishers/consumers only use the interface. Exactly-once semantics are
  enforced at the rating/ledger layer via idempotency keys regardless of the bus.
