# Threat model — Phase 4 (settlement & payments)

Phase 4 crosses into the payment path: AgentOS now moves real money (top-ups in, usage debited,
refunds out) through the Razorpay gateway. Phase 3's worst case corrupted *accounting*; Phase 4's
worst case **moves money wrongly** — credits a wallet for a payment that never cleared, double-
credits, lets a forged webhook mint balance, or lets a depleted tenant keep spending. Scope: the
gateway seam, the top-up lifecycle, wallet reserve/hold, invoicing, and reconciliation. Companion
decision record: [ADR-0010](adr/0010-settlement-payments.md). Builds on the Phase 3 model
([threat-model-phase3.md](threat-model-phase3.md)).

## Assets

- **Settlement correctness** — a wallet is credited if and only if a payment actually cleared, for
  exactly the amount charged, exactly once.
- **The ledger (now with money-in)** — still immutable, complete, and the single source of truth for
  every balance, including top-ups and refunds.
- **Prepaid enforcement** — a depleted balance must stop billable work; a tenant must not spend past
  what they have funded.
- **Gateway secrets** — the key secret and webhook secret authenticate money movement; their leak is
  as severe as a credential leak.
- **Tenant isolation of financial data** — one tenant must never read or affect another's payments,
  invoices, or wallet.

## Trust boundaries

1. Client → API (API key, ADR-0004); all billing endpoints except the webhook are tenant-scoped.
2. **Gateway → API (the webhook)** — the one unauthenticated route; authenticated by HMAC signature
   over the raw body, routed to a tenant by the order `notes` the gateway signs back to us.
3. Runtime/billing → database (Postgres RLS; now also `payment` and `invoice`).
4. Checkout callback (client-relayed) → API — the `razorpay_payment_id`/`signature` the client
   posts are attacker-influenceable and must be verified, never trusted (T11).

## Threats and mitigations (STRIDE-ish)

| # | Threat | Mitigation |
|---|--------|------------|
| T10 | **Forged webhook mints balance** (attacker POSTs a fake `payment.captured`) | The raw body is HMAC-SHA256-verified against the webhook secret **before** it is parsed or applied; a bad signature returns 400 and credits nothing. The tenant is taken from the signed `notes`, so it can't be redirected. |
| T11 | **Tampered checkout callback** (forged `payment_id`/`signature` to confirm an unpaid order) | `confirm` verifies `HMAC(order_id\|payment_id)` against the key secret; a bad signature is recorded as a failed attempt and credits nothing. The amount credited comes from the *stored order*, not the callback, so a client can't inflate it. |
| T12 | **Double-credit** (checkout callback and webhook both report the same payment, or either is replayed) | Credit is a ledger movement unique on `(tenant_id, ref)` (`topup:<payment_id>`), and the `payment.ledger_entry_id` is set under the wallet row's lock; the second arrival credits nothing. Idempotent by construction (ADR-0010 §3). |
| T13 | **Prepaid overrun under concurrency** (a burst each passes the balance check before any debit) | Credit control authorizes against *available* (`balance − reserved`) and reserves the estimate; the real debit releases it, both under the wallet row's lock, so concurrent actions serialize. A depleted balance stops the run `stopped`. Closes the Phase 3 residual risk (ADR-0010 §4). |
| T14 | **Reservation leak** (a step reserves then errors before debiting, stranding funds) | Holds are released co-transactionally by the debit; any still outstanding when the run ends are released by `CreditController.release_all` in the run's `finally`. Reserved never goes below zero. |
| T15 | **Refund abuse / over-refund** (refund more than was paid, or refund a never-settled payment) | A refund is capped at the payment's net (`amount − refunded`), refuses a payment with no `ledger_entry_id`, and is idempotent on `refund:<id>`; it debits the wallet through the ledger like any movement. |
| T16 | **FX/fee mismatch silently loses money** (gateway charges a different amount than we credit) | A payment records both USD credited and gateway minor units charged; reconciliation compares credited top-ups vs gateway charges and flags `gateway_drift` beyond tolerance. |
| T17 | **Silent wallet-projection divergence** (cached balance drifts from the ledger) | Reconciliation re-derives the balance from the ledger (`topups − refunds − usage`) and reports `balance_drift`; non-zero drift raises a critical `reconciliation_drift` alert and the wallet can be rebuilt from the ledger. |
| T18 | **Cross-tenant financial read/write** | `payment` and `invoice` are tenant-scoped under `FORCE ROW LEVEL SECURITY` (migration `0005`); every billing query filters on `tenant_id`; the webhook operates only in the tenant its signed notes name. |
| T19 | **Gateway secret exposure** | Secrets live in env (settings) only, are never logged, never returned by the API, and never sent to the client (only the public `key_id` is). |

## Residual risk / follow-ups

- **Disputes/chargebacks** are modelled as a payment status but automated balance-hold on a dispute
  is future work.
- **Invoice numbering** is a per-tenant count; a concurrent generate could collide on the unique
  `(tenant_id, number)` — acceptable for v0, to be serialized in Phase 5.
- **Scheduled reconciliation / projection-repair** runs on demand via the endpoint; wiring it as a
  periodic job (and auto-rebuilding a drifted wallet) is follow-up.
- **Saved payment methods** depend on the gateway's customer/token APIs and are stubbed until a live
  Razorpay account is connected.
- **RLS is enforced only on Postgres** (migration `0005`); the SQLite dev-fallback mirrors scoping in
  app code — validate isolation on the Postgres stack.
