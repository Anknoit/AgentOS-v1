# Architecture Decision Records

Each ADR captures one load-bearing decision, its context, the options weighed, and the
consequences. ADRs are immutable once **Accepted** — to change a decision, write a new ADR
that supersedes the old one and flip the old one's status to `Superseded by ADR-NN`.

| ADR | Decision | Status |
|-----|----------|--------|
| [ADR-0001](0001-worker-execution-engine.md) | Worker / execution engine: **Arq (Redis)** for v0 | Accepted |
| [ADR-0002](0002-event-bus.md) | Event bus: **NATS** for v0 | Accepted |
| [ADR-0003](0003-usage-store.md) | Usage store: **Postgres table** for v0 | Accepted |
| [ADR-0004](0004-auth-identity.md) | Auth & identity: **API keys + tenant/user tables** for v0 | Accepted |
| [ADR-0005](0005-settlement-vs-byo.md) | First revenue: **BYO keys (Phase 3) before settlement (Phase 4)** | Accepted |
| [ADR-0006](0006-dev-db-fallback.md) | Dev DB fallback: **SQLite + in-process runtime** alongside the Postgres path | Accepted |
| [ADR-0007](0007-agent-runtime-kernel.md) | Agent runtime kernel: **LangGraph with checkpointing** (checkpoint separate from app DB; exactly-once via deterministic keys) | Accepted |
| [ADR-0008](0008-connector-framework.md) | Connector framework: **MCP as the primary protocol**, per-tenant encrypted vault, scope enforced by a runtime broker | Accepted |
| [ADR-0009](0009-metering-rating-budgets.md) | Metering, rating & budgets: **exact integer nanodollars**, versioned rate cards, inline co-transactional rating, append-only ledger, online credit control | Accepted |
| [ADR-0010](0010-settlement-payments.md) | Settlement & payments: **prepaid wallet, Razorpay gateway** behind a swappable seam, ledger-idempotent top-ups, reserve/hold credit control, invoicing + reconciliation | Accepted |

See [TEMPLATE.md](TEMPLATE.md) for the record format.
