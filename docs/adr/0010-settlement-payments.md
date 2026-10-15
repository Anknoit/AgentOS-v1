# ADR-0010: Settlement & payments — prepaid wallet, Razorpay gateway, invoicing, reconciliation

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 4
- **Builds on:** [ADR-0005](0005-settlement-vs-byo.md) (BYO first, settle in Phase 4),
  [ADR-0009](0009-metering-rating-budgets.md) (the ledger/wallet/credit-control core)

## Context

Phase 3 proved metering, rating, and credit control on the tenant's own provider keys (BYO). The
rate card already models `cost` (provider charge) vs `price` (tenant pays), so entering the payment
path is an **additive** step, not a rewrite (ADR-0005). Phase 4 makes AgentOS the payer: one
balance in, usage debited as agents run, one invoice out — "a single point to pay your agents."

Three decisions were load-bearing: which gateway, how to keep accounting exact once real money
moves, and how to close the Phase 3 residual risk that the budget check was not yet a reservation.

## Decision

**1. Gateway: Razorpay, behind a thin swappable seam.** Money-in goes through Razorpay's Orders
API; a payment is confirmed by **HMAC-SHA256 signature verification** on both the checkout callback
(`HMAC(order_id|payment_id)`) and the webhook (`HMAC(raw_body)`). The gateway is an interface with
two implementations: the live `RazorpayGateway` and an in-process `MockGateway` that signs with the
dev secret so the *same* verification code runs hermetically in dev/test (mirrors the mock LLM
provider). Swapping or adding a gateway later touches only this module.

**2. The ledger stays in USD nanodollars; the gateway currency is recorded alongside.** Razorpay
charges in a currency's minor unit (paise/cents). Rather than move the accounting core off USD, a
top-up records both the USD credited (`amount_nanos`) and what the gateway actually charged
(`gateway_amount_minor` + `gateway_currency` at a configurable FX), so a mismatch is reconcilable.

**3. Money-in reuses the append-only ledger with data-layer idempotency.** A top-up/refund is a
ledger movement (`entry_type` `topup`/`refund`), **unique on `(tenant_id, ref)`** where `ref` is the
gateway reference. The two confirmation paths — synchronous checkout callback and asynchronous
webhook — therefore credit the wallet **exactly once** no matter which arrives first or whether both
do. The wallet remains a cached projection of the ledger.

**4. Reserve/hold closes the Phase 3 overrun race.** When a wallet enforces a prepaid balance,
credit control authorizes against **available** funds (`balance − reserved`) and reserves the
estimate before an action; the real debit releases the hold in the same transaction. Concurrent
actions serialize on the wallet row, so a burst can't each pass a check only one of them fits. A
depleted balance stops billable work (the Phase 4 exit gate) through the existing `stopped` path.

**5. Invoicing and reconciliation are ledger projections.** An invoice rolls the period's usage
ledger into line items (by agent + event type) and totals `cost`, `price`, and `margin = price −
cost`. Reconciliation re-derives the balance from the ledger (`topups − refunds − usage`) and
compares credited top-ups against gateway charges; drift beyond tolerance raises an alert.

## Options considered

- **Razorpay (chosen)** — the gateway the team is onboarding; clean Orders + webhook model with
  standard HMAC verification that fits the existing idempotency discipline.
- **Stripe** — equally capable, but not the gateway in use here; the seam means it (or PayPal, or a
  PSP per region) can be added later as another `PaymentGateway` without touching the ledger.
- **Credit money-in outside the ledger (a separate balance table)** — rejected; it would create a
  second source of truth for money and break the "balances are projections" invariant.
- **Keep the Phase 3 authorize-only check** — rejected for the prepaid path; without a reservation a
  concurrent burst can overrun, which is unacceptable once the balance is real money.

## Consequences

- Margin is an accounted ledger quantity from the first settled tenant (markup lifts `price` above
  `cost`; the default card stays markup 0 so BYO numbers still reconcile with providers).
- The webhook is the one unauthenticated route; it is authenticated by signature and routed to a
  tenant by the order `notes` Razorpay signs back to us — no privileged cross-tenant read.
- New surface: `/v1/billing/topups`, `.../confirm`, `/v1/billing/payments`, `.../refund`,
  `/v1/billing/reconciliation`, `/v1/webhooks/razorpay`, `/v1/invoices`, and `PATCH /v1/wallet`.
- **Residual risk / follow-ups:** disputes/chargebacks are recorded but automated hold logic is
  future work; invoice numbering is a per-tenant count (a concurrent generate could race — serialize
  in Phase 5); saved payment methods rely on Razorpay's customer/token APIs and are stubbed until a
  live account; a scheduled reconciliation/projection-repair job is not yet wired (it is on-demand).
- **Reversal cost:** low for the gateway (swap the implementation); high for the money unit and the
  ledger idempotency scheme — those are deliberately the same as Phase 3.
