"""Authentication + tenant resolution (ADR-0004).

A request presents ``Authorization: Bearer <api-key>``. We resolve it to a tenant context,
set it on the request-scoped context (so logs, tracing, and the DB session can read it), and
reject anything unauthenticated. Downstream, every DB access goes through ``tenant_session``,
which applies the Postgres RLS boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select

from app.config.settings import get_settings
from app.core.context import TenantContext, set_tenant
from app.core.errors import AuthError
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session
from app.models.api_key import ApiKey


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
        return TenantContext(tenant_id=row.tenant_id, user_id=row.user_id)


async def require_tenant(
    authorization: Annotated[str | None, Header()] = None,
) -> TenantContext:
    """FastAPI dependency: authenticate and bind the tenant context for the request."""
    ctx = await resolve_api_key(_extract_bearer(authorization))
    set_tenant(ctx)
    return ctx


CurrentTenant = Annotated[TenantContext, Depends(require_tenant)]
