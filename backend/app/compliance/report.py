"""Security-posture report (Phase 6 — the artifact a security review reads).

A single, machine-readable snapshot of the controls that are actually in force for this deployment:
isolation (RLS), encryption + key rotation readiness, SSO/RBAC, audit + retention, fraud controls,
deployment shape + residency. It reads only configuration (no tenant data), so any authenticated
auditor can fetch it, and it doubles as a pre-flight check — ``dev_secrets_in_use`` and a SQLite
backing store are flagged as review blockers for a production/enterprise deployment.
"""

from __future__ import annotations

from typing import Any

from app.config.settings import Settings


def security_posture(settings: Settings) -> dict[str, Any]:
    tenant_isolation = "postgres-rls" if not settings.is_sqlite else "app-scoped (sqlite dev)"
    warnings: list[str] = []
    if settings.dev_secrets_in_use:
        warnings.append("default 'change-me' secrets are in use — rotate before production")
    if settings.is_sqlite and settings.env == "prod":
        warnings.append("SQLite dev-fallback in a prod environment — move to Postgres for RLS")
    if settings.sso_mode == "mock" and settings.env == "prod":
        warnings.append("SSO is in mock mode — configure a real OIDC issuer for production")
    if settings.cors_origins == ["*"] and settings.env == "prod":
        warnings.append("CORS allows all origins — restrict for production")

    return {
        "deployment_mode": settings.deployment_mode,
        "single_tenant": settings.single_tenant_id is not None,
        "data_region": settings.data_region,
        "environment": settings.env,
        "tenant_isolation": tenant_isolation,
        "encryption": {
            "credentials_at_rest": "per-tenant-fernet-hkdf",
            "key_rotation_ready": len(settings.secret_key_fallbacks) > 0,
        },
        "identity": {
            "rbac_enabled": settings.rbac_enabled,
            "sso_mode": settings.sso_mode,
            "api_keys": "hashed (sha256 + pepper)",
        },
        "audit": {
            "enabled": settings.audit_log_enabled,
            "retention_days": settings.data_retention_days,
            "ledger_retention": "permanent (immutable financial record)",
        },
        "fraud_controls": {
            "enabled": settings.fraud_enabled,
            "run_velocity_per_window": settings.fraud_run_velocity_limit,
            "topup_velocity_per_window": settings.fraud_topup_velocity_limit,
            "hold_on_anomaly": settings.fraud_hold_on_anomaly,
        },
        "dev_secrets_in_use": settings.dev_secrets_in_use,
        "review_warnings": warnings,
        "review_ready": len(warnings) == 0,
    }
