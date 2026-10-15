# ADR-0004: Auth & identity — API keys + tenant/user tables for v0

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 0

## Context

Every row, event, and log line carries `tenant_id`, enforced at the data layer (Postgres RLS).
Requests must resolve to a tenant before touching data. The plan's endgame is an **OIDC
provider (Clerk/Auth0)** with SSO/SAML for enterprise (Phase 6), but Phase 0 only needs enough
identity to (a) authenticate a caller, (b) resolve its tenant, and (c) thread `tenant_id`
through every request.

## Decision

Ship **API keys backed by `tenant`, `user`, and `api_key` tables** for v0. A request presents
`Authorization: Bearer <key>`; a dependency resolves it to `(tenant_id, user_id)`, sets the
Postgres session GUC `app.current_tenant` so RLS applies, and rejects unauthenticated or
cross-tenant access. API keys are stored as salted hashes, never in plaintext. Graduate this
skeleton to OIDC in Phase 6 without changing the `tenant_id`-everywhere contract.

## Options considered

- **API keys + local tables** — zero external dependency, instantly testable, exactly the
  surface the runtime and the client SDK need now. Cost: no SSO, no user-facing login UX; fine
  for v0 and self-hosted.
- **OIDC (Clerk/Auth0) now** — real login, MFA, SSO out of the box. Cost: external dependency
  and integration work before we have a product to log into; premature.

## Consequences

- Auth is a single dependency (`core/auth.py`) that produces the request's tenant context;
  swapping in OIDC later means changing how `(tenant_id, user_id)` is derived, not the
  downstream contract.
- API keys remain useful forever for service-to-service and CI auth even after OIDC lands.
- **Reversal cost:** low — the tenant-context seam is stable; Phase 6 adds an identity provider
  in front of it.
