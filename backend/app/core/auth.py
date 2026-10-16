"""Authentication + tenant resolution (ADR-0004, extended for SSO in Phase 6 — ADR-0012).

A request presents ``Authorization: Bearer <token>``. The token is either an **API key**
(``ak_...``, resolved against the ``api_key`` table) or an **SSO JWT** (verified against the
configured IdP — see ``identity.oidc``). Either way we resolve it to a tenant context carrying the
principal's **role** (for RBAC), set it on the request-scoped context, and reject anything
unauthenticated. Downstream, every DB access goes through ``tenant_session`` (the Postgres RLS
boundary). In self-hosted single-tenant mode the resolved tenant is pinned to
``settings.single_tenant_id``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select

from app.config.settings import Settings, get_settings
from app.core.context import TenantContext, set_tenant
from app.core.errors import AuthError, ForbiddenError
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.models.user import User


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing or malformed Authorization header")
    return authorization.split(" ", 1)[1].strip()


async def resolve_api_key(raw_key: str) -> TenantContext:
    settings = get_settings()
    expected_hash = hash_api_key(raw_key, pepper=settings.api_key_pepper)
    async with system_session() as session:
        row = (
            await session.execute(
                select(ApiKey).where(
                    ApiKey.prefix == key_prefix(raw_key),
                    ApiKey.key_hash == expected_hash,
                    ApiKey.revoked.is_(False),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise AuthError("invalid API key")
        row.last_used_at = datetime.now(timezone.utc)
        return _pin(
            TenantContext(
                tenant_id=row.tenant_id,
                user_id=row.user_id,
                role=row.role,
                auth_method="api_key",
            ),
            settings,
        )


async def resolve_sso_token(raw_token: str, settings: Settings) -> TenantContext | None:
    """Verify an SSO JWT and map it to a tenant principal, or ``None`` if it isn't an SSO token.

    The ``tenant`` claim names a tenant by slug or id; the ``email`` claim is matched to a ``user``
    row to inherit its stored role (a claim ``role`` overrides). A token for an unknown tenant is
    rejected — SSO authenticates an *existing* tenant's members, it doesn't provision tenants.
    """
    from app.identity.oidc import verify_token

    claims = verify_token(raw_token, settings)
    if claims is None:
        return None
    if not claims.tenant:
        raise AuthError("SSO token has no tenant/org claim")

    async with system_session() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(
                    (Tenant.id == claims.tenant) | (Tenant.slug == claims.tenant)
                )
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise AuthError(f"SSO token references unknown tenant '{claims.tenant}'")

        user = None
        if claims.email:
            user = (
                await session.execute(
                    select(User).where(
                        User.tenant_id == tenant.id, User.email == claims.email
                    )
                )
            ).scalar_one_or_none()

        role = claims.role or (user.role if user is not None else "member")
        return _pin(
            TenantContext(
                tenant_id=tenant.id,
                user_id=user.id if user is not None else claims.subject,
                role=role,
                auth_method="sso",
            ),
            settings,
        )


def _pin(ctx: TenantContext, settings: Settings) -> TenantContext:
    """Enforce self-hosted single-tenant isolation: refuse a principal for any other tenant."""
    if settings.single_tenant_id and ctx.tenant_id != settings.single_tenant_id:
        raise ForbiddenError("this instance serves a single tenant", code="wrong_tenant")
    return ctx


async def resolve_bearer(raw_token: str) -> TenantContext:
    """Resolve a bearer token: an SSO JWT if it is one and SSO is on, else an API key."""
    settings = get_settings()
    ctx = await resolve_sso_token(raw_token, settings)
    if ctx is not None:
        return ctx
    return await resolve_api_key(raw_token)


async def require_tenant(
    authorization: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """FastAPI dependency: authenticate and bind the tenant context for the request."""
    ctx = await resolve_bearer(_extract_bearer(authorization))
    set_tenant(ctx)
    return ctx


CurrentTenant = Annotated[TenantContext, Depends(require_tenant)]
