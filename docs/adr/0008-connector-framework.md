# ADR-0008: Connector framework — MCP as the primary protocol

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 2

## Context

Phase 2 lets agents touch real systems (Slack, a CRM, the web) with permissions and credentials
as first-class, scoped objects. The exit criterion: a Support Desk agent reads from and posts to
Slack and a CRM using scoped, tenant-isolated credentials, and an attempt to use an ungranted
scope is denied and logged. The development plan names **MCP (Model Context Protocol) as the
primary protocol** for connectors.

The decisions: what shape a connector takes (so built-ins and third-party apps are
interchangeable), where credentials live and how they are protected, and where permission is
actually enforced so an agent can never exceed its grant.

## Decision

1. **Everything is an MCP server behind one `MCPSession`.** A connector — built-in or third-party
   — exposes tools and is driven through the identical surface: `initialize → list_tools →
   call_tool`. Built-ins are **in-process MCP servers** (`InProcessMCPSession` over async Python
   handlers); third-party apps are reached with a **spec-faithful JSON-RPC 2.0 client over the
   Streamable HTTP transport** (`RemoteMCPSession`), including the protocol-version/capability
   handshake and the `tools/list` / `tools/call` methods. The runtime never branches on "is this
   built-in or remote" — that is the point of using MCP as the spine.

2. **Capabilities are the coarse grant, scopes the fine grant.** A small closed vocabulary of
   capabilities (`messaging`, `data`, `web`; voice deferred to Phase 5) classifies connectors;
   each tool declares the capability it belongs to and the **scope** it needs (e.g. `chat:write`
   vs `channels:read`). An `agent_version`'s `connector_bindings` grant connectors and scopes
   explicitly; nothing is ambient.

3. **Credentials are encrypted per tenant, decrypted only at call time.** A `credential` row
   stores a Fernet ciphertext of the secret, encrypted under a key **derived per tenant** from the
   deployment master secret via HKDF (ADR-0006's RLS still applies — this is defence in depth: RLS
   stops cross-tenant reads, per-tenant encryption makes a leaked row useless to another tenant).
   The plaintext is never persisted, never returned by the API, and never logged (only a redacted
   `••••abcd` hint). `expires_at` lets the vault refuse a stale token.

4. **One enforcement point: the `ConnectorBroker`.** Every connector call an agent makes goes
   through the broker, constructed per run with exactly that run's grants and no ambient authority.
   It resolves tool → connector → required scope, checks the grant, and on a miss **denies and
   logs** (`connector_call` action, `outcome="denied"`) and raises `ScopeDeniedError` *before* any
   credential is touched or anything is metered. On a grant it loads the credential, invokes the
   session, meters one `usage_event` with the Phase 1 deterministic idempotency key
   (`{run_id}:step{seq}:connector:{tool}`), and appends an audit row. Granted or denied, a
   connector call is always attributable.

5. **A generic MCP connector is the escape hatch.** The `mcp` connector points at any third-party
   MCP server (URL + token from the bound credential), so new apps plug in without new code — the
   whole framework is wire-compatible with the ecosystem.

## Options considered

- **Bespoke per-connector interfaces (no shared protocol).** Simple for the first connector, but
  every new integration reinvents discovery, invocation, and error handling, and third-party
  servers have no path in. Rejected: MCP gives discovery + invocation + an ecosystem for free.
- **Adopt the full MCP SDK now.** Most spec-complete. Cost: a heavier dependency and less control
  over the offline/deterministic test story. Rejected *for now* — the transport is abstracted
  behind a `Transport` protocol, so the SDK (or a stdio transport) can slot in later without
  touching callers. The hand-written client targets protocol revision `2025-06-18`.
- **Enforce scope inside each connector.** Puts the security check next to the integration. Cost:
  every connector must get it right, and a bug is a privilege escalation. Rejected: a single broker
  is the one place to audit, and it enforces *before* the connector (and its credential) is reached.
- **Store credentials with a single app-wide key / env vars.** Simpler ops. Cost: one leaked key
  exposes every tenant, and env vars don't scale to many tenants × connectors. Rejected for the
  per-tenant derived key.

## Consequences

- Built-in connectors ship as deterministic offline stubs (like the Phase 1 `kb_search` tool), so
  the full path — discover → bind → scope-check → decrypt → call → meter → audit — runs in CI with
  no network or real secrets. Going live is a change inside one handler.
- `connector_call` joins `model_call` and `tool_call` as a metered `usage_event` type, so Phase 3
  rating prices connector usage with no new plumbing.
- The checkpoint/exactly-once guarantees from ADR-0007 extend to connectors unchanged: a replayed
  step re-uses the same idempotency key and re-appends the same audit row.
- Rotating `AGENTOS_SECRET_KEY` invalidates stored ciphertext; `MultiFernet` leaves room to add a
  rotation path (decrypt-old / encrypt-new) without a schema change.
- A full threat model for this phase lives in [docs/threat-model-phase2.md](../threat-model-phase2.md).
