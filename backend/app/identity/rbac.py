"""Role-based access control (Phase 6, build task 2).

Granular, data-driven permissions over agents, spend, connectors, billing, members, and audit.
A principal (an API key or an SSO user) carries a **role**; a write endpoint declares the
**permission** it needs; the :data:`Scoped` dependency checks one against the other.

Roles are coarse-grained bundles of fine-grained permissions, so new endpoints map to a
permission string and inherit the right role gates with no role-table churn:

* ``owner``   — everything (the account root; what existing keys default to, so nothing breaks).
* ``admin``   — everything except destroying the account / transferring ownership (same perms here).
* ``billing`` — spend + billing read/write, read elsewhere (a finance seat).
* ``operator``— run and operate agents/connectors; no billing writes, no member management.
* ``member``  — build and run agents; read spend; no billing, members, or audit.
* ``auditor`` — read-only everywhere, including the audit log (a security-review seat).

The permission vocabulary is ``<resource>:<read|write>``. ``admin:write`` gates operator actions
(fraud holds, retention, key rotation).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.config.settings import get_settings
from app.core.auth import require_tenant
from app.core.context import TenantContext
from app.core.errors import ForbiddenError

# Every permission the system knows about — the authoritative vocabulary.
ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        "agents:read",
        "agents:write",
        "runs:read",
        "runs:write",
        "connectors:read",
        "connectors:write",
        "spend:read",
        "billing:read",
        "billing:write",
        "members:read",
        "members:write",
        "audit:read",
        "marketplace:read",
        "marketplace:write",
        "admin:write",
    }
)

_READ_ONLY: frozenset[str] = frozenset(p for p in ALL_PERMISSIONS if p.endswith(":read"))

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS,
    "billing": _READ_ONLY | {"billing:write", "marketplace:write"},
    "operator": _READ_ONLY
    | {"agents:write", "runs:write", "connectors:write", "marketplace:write"},
    "member": frozenset(
        {"agents:read", "agents:write", "runs:read", "runs:write", "connectors:read",
         "spend:read", "marketplace:read"}
    ),
    "auditor": _READ_ONLY,
}

# A role we don't recognise gets the safe floor: read-only.
_DEFAULT_ROLE_PERMS = _READ_ONLY

VALID_ROLES: frozenset[str] = frozenset(ROLE_PERMISSIONS)


def permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, _DEFAULT_ROLE_PERMS)


def has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for(role)


def require_permission(ctx: TenantContext, permission: str) -> None:
    """Raise ``ForbiddenError`` unless ``ctx.role`` grants ``permission`` (no-op if RBAC is off)."""
    if not get_settings().rbac_enabled:
        return
    if not has_permission(ctx.role, permission):
        raise ForbiddenError(
            f"role '{ctx.role}' is not permitted to '{permission}'", code="forbidden"
        )


def _require_perm(permission: str):
    async def dep(ctx: Annotated[TenantContext, Depends(require_tenant)]) -> TenantContext:
        require_permission(ctx, permission)
        return ctx

    return dep


def Scoped(permission: str):  # noqa: N802 - reads as a type annotation at call sites
    """A dependency that authenticates **and** enforces ``permission``.

    Usage: ``tenant: Annotated[TenantContext, Scoped("agents:write")]``. The owner/admin roles pass
    everything, so it is a drop-in tightening of an endpoint that used ``CurrentTenant``.
    """
    return Depends(_require_perm(permission))
