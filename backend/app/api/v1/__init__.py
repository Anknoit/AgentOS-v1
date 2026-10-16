from fastapi import APIRouter

from app.api.v1 import (
    admin,
    agents,
    auth,
    billing,
    compliance,
    connectors,
    marketplace,
    members,
    meta,
    ops,
    runs,
    spend,
    usage,
)

api_router = APIRouter()
api_router.include_router(meta.router, tags=["meta"])
api_router.include_router(auth.router, prefix="/auth", tags=["identity"])
api_router.include_router(members.router, prefix="/members", tags=["identity"])
api_router.include_router(members.api_keys_router, prefix="/api-keys", tags=["identity"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(usage.router, prefix="/usage", tags=["usage"])
api_router.include_router(connectors.router, prefix="/connectors", tags=["connectors"])
api_router.include_router(
    connectors.credentials_router, prefix="/credentials", tags=["connectors"]
)
api_router.include_router(spend.spend_router, prefix="/spend", tags=["metering"])
api_router.include_router(spend.wallet_router, prefix="/wallet", tags=["metering"])
api_router.include_router(spend.ratecards_router, prefix="/rate-cards", tags=["metering"])
api_router.include_router(spend.budgets_router, prefix="/budgets", tags=["metering"])
api_router.include_router(spend.alerts_router, prefix="/alerts", tags=["metering"])
api_router.include_router(billing.billing_router, prefix="/billing", tags=["billing"])
api_router.include_router(billing.invoices_router, prefix="/invoices", tags=["billing"])
api_router.include_router(billing.webhook_router, prefix="/webhooks", tags=["billing"])
api_router.include_router(ops.router, prefix="/ops", tags=["ops"])
api_router.include_router(compliance.audit_router, prefix="/audit", tags=["compliance"])
api_router.include_router(compliance.router, prefix="/compliance", tags=["compliance"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(marketplace.router, prefix="/marketplace", tags=["marketplace"])

__all__ = ["api_router"]
