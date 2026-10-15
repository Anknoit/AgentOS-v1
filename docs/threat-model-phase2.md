# Threat model — Phase 2 (connector framework)

Credential handling and scope enforcement are where a breach would be worst, so Phase 2 is
threat-modelled on its own. Scope: the connector framework — the credential vault, the
`ConnectorBroker`, built-in connectors, and the remote MCP path. Companion decision record:
[ADR-0008](adr/0008-connector-framework.md).

## Assets

- **Connector credentials** (OAuth tokens, API keys) — the crown jewels; grant access to tenants'
  external systems (Slack workspaces, CRM data).
- **Tenant isolation** — one tenant must never read, use, or infer another's credentials or data.
- **The audit trail** — every connector call must be attributable (who, which agent/version, which
  scope, granted or denied).

## Trust boundaries

1. Client → API (authenticated by API key, ADR-0004).
2. API/runtime → database (tenant boundary enforced by Postgres RLS, ADR-0006).
3. Runtime → **third-party connector endpoints** (new in Phase 2; data leaves our perimeter).
4. Agent model output → connector arguments (the model is **untrusted input**, not a trusted
   caller).

## Threats and mitigations (STRIDE-ish)

| # | Threat | Mitigation |
|---|--------|------------|
| T1 | **Credential theft from the DB** (dump, backup, SQLi) | Secrets encrypted at rest with a **per-tenant** HKDF-derived Fernet key (ADR-0008 §3). A leaked row is undecryptable without the master secret *and* is bound to its tenant's derived key. RLS (defence in depth) blocks cross-tenant reads in the first place. |
| T2 | **Cross-tenant credential use** | The broker resolves credentials only for its run's `tenant_id`; the vault derives the decryption key from that same `tenant_id`, so even a mis-scoped query can't yield usable plaintext for another tenant. |
| T3 | **Privilege escalation — agent calls an ungranted connector/scope** | Single enforcement point (`ConnectorBroker`) checks the `agent_version` grant **before** the credential is loaded or the connector reached; a miss is denied, logged, and raises. No connector self-enforces. |
| T4 | **Credential leakage via logs / API / errors** | Plaintext is never persisted, never returned by any endpoint (credentials are write-only over the API), and never logged — only a redacted `••••abcd` hint. Audit rows record argument *shape*, truncating long strings. |
| T5 | **Confused-deputy via model output** | The model can only name tools; the broker maps names to fixed scopes and refuses anything outside the grant. The model cannot widen scope, pick a connector it wasn't granted, or supply its own credential. |
| T6 | **Malicious / compromised third-party MCP server** | The server only ever receives the arguments for the one tool called and the token for *its* connector — never other connectors' credentials. Scope is enforced our side before the call. (Hardening still owed: egress allow-listing, response-size limits — partially done via the HTTP connector's body cap — and per-call timeouts.) |
| T7 | **Replay / double-spend of a connector action** | Deterministic idempotency key (`{run_id}:step{seq}:connector:{tool}`) means a replayed step after a resume re-uses the same `usage_event` and re-appends the same audit row (ADR-0007 carried into Phase 2). |
| T8 | **Stale/expired token used** | `expires_at` on the credential; the vault refuses an expired credential rather than calling with it. |
| T9 | **Tampered ciphertext** | Fernet is authenticated (HMAC-SHA256); decrypt fails closed with `CryptoError` rather than yielding forged plaintext. |

## Residual risk / follow-ups

- **Egress controls** for the remote MCP + HTTP connectors (SSRF to internal networks, DNS
  rebinding): add an allow-list and block private IP ranges. Tracked for the full Postgres/compose
  hardening pass.
- **OAuth refresh**: refresh-token rotation is stubbed (`expires_at` + room in the ciphertext
  envelope) but not yet automatic.
- **Secret rotation**: `MultiFernet` supports it; the decrypt-old/encrypt-new migration path is not
  yet built.
- **Rate limiting / quotas per connector** land with budgets in Phase 3.
