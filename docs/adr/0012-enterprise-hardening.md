# ADR-0012: Enterprise & hardening — RBAC/SSO, compliance, fraud controls, marketplace, self-hosted

- **Status:** Accepted
- **Date:** 2026-10-16
- **Deciders:** AgentOS core team
- **Phase:** 6
- **Builds on:** [ADR-0004](0004-auth-identity.md) (API keys + tenant/user tables — now graduated),
  [ADR-0008](0008-connector-framework.md) (per-tenant vault — now with key rotation),
  [ADR-0009](0009-metering-rating-budgets.md) (ledger, anomalies — now the fraud signal),
  [ADR-0006](0006-dev-db-fallback.md) (the swappable-seam + hermetic-default discipline)

## Context

Phases 0–5 built a correct, scalable accounting core. Phase 6 clears the trust-and-expansion bars a
product that holds money, credentials, and a whole agent fleet must meet: an enterprise tenant must
onboard with **SSO and scoped roles**, pass a **security review**, and run on **isolated or
self-hosted** infrastructure with **full audit export**. None of this may weaken the metering /
settlement core, and — per the standing constraint — anything an enterprise would wire to real infra
(an OIDC issuer, a shared rate-limit store, read replicas, a customer's own server) must sit behind a
seam with a hermetic in-process default so the whole system still boots, tests, and demos offline.

## Decision

**1. RBAC is data-driven; the principal carries a role.** A principal — an API key *or* an SSO user
— carries a `role`; each write endpoint declares the `permission` it needs (`<resource>:<read|write>`);
a `Scoped(perm)` dependency checks one against the other. Roles (`owner`, `admin`, `billing`,
`operator`, `member`, `auditor`) are bundles of permissions, so a new endpoint maps to a permission
string with no role-table churn. `owner` grants everything, so every pre-existing key keeps working.
API keys gained a `role` column, so a tenant can mint **scoped keys** (a read-only auditor key, a
CI key limited to runs) without a user login.

**2. SSO graduates the API-key skeleton behind a seam, without replacing it.** A bearer token that
parses as a JWT is verified by `identity.oidc` and mapped to a tenant principal; anything else stays
an API key — the two coexist during a migration. `AGENTOS_SSO_MODE` selects the backend: `none`
(default), `mock` (HS256 signed with the SSO secret — a hermetic, offline IdP, the enterprise
analogue of the mock payment gateway), or `oidc` (RS256 verified against a real issuer's JWKS — the
only mode that touches the network). SSO authenticates an *existing* tenant's members; it does not
provision tenants.

**3. Audit logging is a second, control-plane trail — append-only, tenant-scoped, exportable.**
`action_log` records what an agent *run* did; `audit_log` records what a *principal* did to the
account (created an agent, stored a credential, minted a key, changed a role, topped up, rotated
keys, published to the marketplace). It is written in its own committed transaction and is
best-effort relative to the operation (auditing never breaks a working endpoint). Secrets are never
audited — only the fact one was stored. The trail is exportable for a review.

**4. Key rotation uses `MultiFernet`, zero-downtime, no schema change.** The per-tenant vault
(ADR-0008) now encrypts through a `MultiFernet` over the current secret plus `secret_key_fallbacks`.
Rotation is two steps: put the new secret in front and the old in the fallbacks (everything still
decrypts), then `agentos rotate-keys` re-encrypts every ciphertext under the current secret so the
old one can be dropped. Only ciphertext changes; no plaintext ever lands on disk.

**5. Data retention purges operational rows; the money ledger is immutable.** Retention deletes
runs, action logs, event logs, and alerts older than `AGENTOS_DATA_RETENTION_DAYS`. It **never**
touches `ledger_entry` / `invoice` / `payment` / `usage_event` — financial record is kept
permanently for reconciliation and disputes, regardless of the horizon. Residency is a `region`
label pinned on a tenant at creation and surfaced in the posture report; moving data across regions
is an explicit migration, not a field edit.

**6. Fraud/abuse controls converge on one primitive — the tenant hold.** Velocity limits (a sliding
in-process window per `(tenant, kind)`, the Redis seam at scale) cap how fast a tenant starts runs
or confirms top-ups; tripping one places a hold *and* raises (so abuse stops, not just throttles).
Recent critical anomalies (a runaway loop — ADR-0009) are promoted to a hold by an operator scan,
**off** the metering hot path so it never contends with the rating transaction. While a hold is
active the run/top-up path refuses billable work (`TenantHeldError`) — a per-tenant circuit breaker;
an operator releases it, and the hold row is kept as audit.

**7. The marketplace is the one deliberately cross-tenant table.** `marketplace_listing` is a public
catalogue (outside RLS), accessed only through `system_session`. Publishing copies an agent's
immutable version config or a connector's non-secret `provider_meta`; **no secret is ever
published**. Installing copies the config into the caller's own tenant through the normal
tenant-scoped services, so isolation holds everywhere except the shared catalogue itself, and the
installer brings their own credentials.

**8. Self-hosted is a single-tenant pin, not a fork.** The same binary serves on-prem; setting
`AGENTOS_SINGLE_TENANT_ID` makes the auth layer refuse any principal that resolves to a different
tenant (hard isolation), and `AGENTOS_DEPLOYMENT_MODE` + `region` are surfaced in `/health` and the
posture report. The security-posture report (`GET /v1/compliance/report`, `agentos posture`) is the
review artifact: it reads only configuration and flags review blockers (default secrets, SQLite in
prod, mock SSO in prod, open CORS).

## Consequences

- **Positive:** the Phase 6 exit criterion is demonstrable end to end (SSO login → scoped role →
  denied write → audit export → fraud hold → marketplace install), proven in tests and the live
  smoke run. Nothing in the accounting core changed; migration `0007` is purely additive. Every new
  dependency (OIDC issuer, shared counter store, replicas, customer server) is a flagged seam over a
  hermetic default, so the zero-dependency dev profile still boots and all prior tests pass unchanged.
- **Negative / follow-ups:** the velocity counters are in-process (fine for a single node and the
  dev profile; a multi-node deployment needs the Redis seam, as with the Phase 5 scheduler). The
  anomaly→hold promotion is a scan, not yet a scheduled job. The `oidc` mode is wired but exercised
  only against the `mock` IdP in CI (a real issuer is an integration test). RLS on the new tables is
  enforced only on Postgres (migration `0007`); the SQLite dev-fallback mirrors scoping in app code.
  SOC 2 is a controls-and-evidence program — this phase builds the technical controls (audit,
  retention, encryption/rotation, RBAC, residency), not the certification.

## Alternatives considered

- **Replace API keys with OIDC outright.** Rejected: it would break every existing integration and
  the hermetic dev profile. Coexistence behind one bearer path is a migration, not a flag day.
- **A full external IdP in dev (Keycloak in compose).** Rejected as the *default*: it violates the
  offline-boot constraint. The mock HS256 IdP gives the same code path with no dependency; real OIDC
  is one setting away.
- **Enforce the marketplace catalogue under RLS like everything else.** Rejected: a catalogue is
  inherently cross-tenant. Keeping it the single, explicit exception (system-session only, no
  secrets) is safer than threading a "public" predicate through the RLS policies.
- **Delete old data on a retention horizon uniformly.** Rejected for money: the ledger is immutable
  financial record. Retention is scoped to operational telemetry only.
