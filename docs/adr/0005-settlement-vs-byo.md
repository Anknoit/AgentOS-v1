# ADR-0005: First revenue — BYO keys (Phase 3) before settlement (Phase 4)

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** AgentOS core team
- **Phase:** 0

## Context

The defensible core is metering → rating → ledger → real-time credit control. The hardest and
riskiest part is **settlement** (being the payer: Stripe, invoicing, reconciliation, float,
money-movement correctness). The plan ships metering + control **on your own provider keys**
in Phase 3, then settlement in Phase 4. The open question is how long to stay BYO before
entering the payment path.

## Decision

Ship a **bring-your-own-keys (BYO) tier first**: in Phase 3 the tenant supplies their own
provider keys; AgentOS meters, rates, and enforces budgets/caps but does **not** move money.
Settlement (prepaid wallet, Stripe, invoicing, reconciliation) lands in **Phase 4**. BYO proves
the control story and earns revenue on control value before we take on payment-path risk. Enter
settlement once the rating numbers reconcile against provider bills within tolerance (the
Phase 3 exit gate) and there is demand to be the single payer.

## Options considered

- **BYO first, settlement in Phase 4 (chosen)** — de-risks the hardest part; revenue from the
  control story earlier; the rate card already models `cost` vs `price` so settlement is an
  additive step, not a rewrite.
- **Settlement from the start** — captures margin immediately, but front-loads the highest-risk
  work (float, disputes, reconciliation) before metering accuracy is proven. Rejected.

## Consequences

- The `rate_card` carries both `cost` and `price` from Phase 3 so margin is an accounted
  quantity the moment settlement switches on.
- No Stripe / money movement before Phase 4; budgets in Phase 3 enforce **spend control**, not
  payment.
- **Reversal cost:** n/a — this is a sequencing decision, and Phase 4 builds on Phase 3 rather
  than replacing it.
