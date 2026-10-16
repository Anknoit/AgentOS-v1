# Threat model — Phase 6 (enterprise & hardening)

Phase 6 adds RBAC + SSO, a control-plane audit trail, key rotation, data retention/residency,
fraud/abuse holds, a cross-tenant marketplace, and a self-hosted single-tenant mode. These are the
controls a security review probes — and each is also a new way the system could be *weakened*: a
role that over-grants, a forged SSO token, an audit gap, a rotation that strands ciphertext, a
retention job that eats the ledger, a marketplace listing that leaks a secret or escapes tenant
isolation, a self-hosted instance that serves the wrong tenant. Scope: identity (`identity/*`,
`core.auth`), compliance (`compliance/*`), fraud (`fraud/*`), marketplace (`marketplace/*`).
Companion record: [ADR-0012](adr/0012-enterprise-hardening.md). Builds on the Phase 2–5 models.

## Assets

- **Least privilege** — a principal can do only what its role grants; a scoped key or SSO user can't
  escalate by calling an endpoint it wasn't granted.
- **Authentication integrity** — only tokens this deployment issued (an API key, or a JWT from the
  configured IdP) authenticate; a forged/expired/foreign token does not.
- **The audit trail** — a faithful, tamper-evident, tenant-isolated record of control-plane actions,
  complete enough for a review and never containing secrets.
- **Credential confidentiality across rotation** — a master-key rotation never strands ciphertext
  and never writes plaintext to disk.
- **The money ledger's permanence** — retention and purges never delete financial record.
- **Tenant isolation, including the one public table** — the marketplace is cross-tenant *by design*
  for catalogue reads only; installs and everything else stay tenant-scoped, and no secret is shared.

## Trust boundaries

1. Client → API: an API key *or* an SSO JWT. The JWT path adds a new issuer trust boundary (the IdP
   / its JWKS).
2. Role → permission: the authenticated principal's role is checked at each write endpoint.
3. Operator → CLI (`rotate-keys`, `retention`, `posture`) — local, privileged, DB credentials.
4. Tenant ↔ marketplace: a cross-tenant catalogue; the only sanctioned cross-tenant data flow, and
   only for non-secret listing config.
5. Self-hosted operator → a single-tenant instance pinned to one tenant id.

## Threats and mitigations (STRIDE-ish)

| # | Threat | Mitigation |
|---|--------|------------|
| T30 | **Privilege escalation via RBAC** (a low-privilege role performs a write it shouldn't) | Every write endpoint is gated by `Scoped(permission)`; roles are fixed permission bundles and an unknown role falls to read-only. `owner` is the only all-permissions role. Proven in `test_rbac` (auditor/member denied writes) and the smoke run. |
| T31 | **Forged / foreign SSO token** (a hand-crafted or another deployment's JWT authenticates) | `identity.oidc` verifies signature + `iss` (+ `aud` for OIDC) and requires `exp`/`sub`; a JWT that fails is *rejected* (`AuthError`), never silently treated as an API key. SSO maps only to an existing tenant — it can't provision one. Proven in `test_sso_oidc`. |
| T32 | **SSO token for tenant A used against tenant B** | The tenant is taken from the signed `tenant`/`org` claim and resolved to a real tenant; the principal is pinned to that tenant, and in self-hosted mode to `single_tenant_id`. RLS still scopes every query under that tenant. |
| T33 | **Audit gap** (a mutation leaves no trail, or auditing failure breaks the endpoint) | Mutating endpoints call `audit(...)` which writes an append-only `audit_log` row in its own committed transaction; a write that rolls back still leaves the audit entry, and an audit failure is logged, never raised. `test_audit` asserts the trail and tenant isolation. |
| T34 | **Secret leak through the audit trail** | Audit context records identifiers and the *fact* of an action, never secrets; the credential-store audit carries connector key + name only. `test_audit` asserts the plaintext secret never appears. |
| T35 | **Cross-tenant audit read** | `audit_log` is tenant-scoped under `FORCE ROW LEVEL SECURITY` (migration `0007`); `GET /v1/audit` runs in the caller's `tenant_session`; `audit:read` gates it. `test_audit` proves B sees none of A's entries. |
| T36 | **Key rotation strands or exposes credentials** | Rotation uses `MultiFernet` (decrypt with current *or* fallback, encrypt with current); ciphertext written under the old secret keeps decrypting until `rotate-keys` re-encrypts it, and plaintext is never persisted. `test_key_rotation` proves a credential survives a full rotation and still decrypts after the old secret is dropped. |
| T37 | **Retention deletes financial record** | The purge targets only operational tables (`run`, `action_log`, `event_log`, `alert`); `ledger_entry`/`invoice`/`payment`/`usage_event` are never in scope. `test_compliance` asserts old runs purge while the ledger is untouched; `0` days is a no-op. |
| T38 | **Marketplace leaks a secret or escapes isolation** | Publishing copies only non-secret config (version config / `provider_meta`); credentials are never read or published. Listings live in the one non-RLS table, reached only via `system_session`; installs write into the caller's tenant through tenant-scoped services. `test_marketplace` asserts a connector listing carries no secret and an install lands a fresh agent in the installer's tenant. |
| T39 | **Prepaid / run abuse** (stolen-card top-up cycling, run flooding) | Per-tenant velocity limits on runs and top-ups; a breach raises (`VelocityError`, 429) and places a hold that blocks further billable work (`TenantHeldError`, 403) until an operator releases it. Anomaly-driven holds promote runaway-loop criticals. `test_fraud_controls` + the smoke run prove block/release. |
| T40 | **Self-hosted instance serves the wrong tenant** (misconfig exposes other tenants' data) | `single_tenant_id` makes `core.auth` refuse any principal resolving to a different tenant (`wrong_tenant`, 403); the posture report flags prod misconfig (default secrets, SQLite, open CORS, mock SSO). `test_compliance` proves the pin. |

## Residual risk / follow-ups

- **Velocity counters are in-process** — correct for a single node and the dev profile; a multi-node
  deployment needs the shared-store (Redis) seam, like the Phase 5 scheduler.
- **Anomaly→hold is an operator scan**, not yet a scheduled job; a cron/worker should run it.
- **OIDC mode is wired but CI-exercised only against the mock IdP**; a real issuer is an integration
  test (JWKS fetch, clock skew, key rollover).
- **RLS is enforced only on Postgres** (migration `0007`); the SQLite dev-fallback mirrors scoping in
  app code — validate isolation (and the marketplace's deliberate exception) on the Postgres stack.
- **SOC 2 is a program, not a feature** — this phase builds the technical controls and their
  evidence (audit export, posture report); the certification (policies, vendor reviews, continuous
  monitoring) is organizational follow-up.
- **Backup/retention encryption** remains an operational control (Phase 5 T27), not enforced in code.
