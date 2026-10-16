"""Shared test helpers for Phase 6 (identity/compliance/fraud/marketplace)."""

from __future__ import annotations

from app.config import get_settings
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.models.user import User
from app.services.ratecards import ensure_default_card


async def new_tenant_with_key(slug: str, *, role: str = "owner") -> tuple[str, str]:
    """Create a tenant + user + API key with a known plaintext. Returns ``(tenant_id, raw_key)``."""
    s = get_settings()
    raw_key = f"key-{slug}-{role}"
    async with system_session() as session:
        tenant = Tenant(slug=slug, name=slug)
        session.add(tenant)
        await session.flush()
        tid = tenant.id
        user = User(tenant_id=tid, email=f"{slug}@t.local", role=role)
        session.add(user)
        await session.flush()
        session.add(
            ApiKey(
                tenant_id=tid,
                user_id=user.id,
                name="k",
                role=role,
                prefix=key_prefix(raw_key),
                key_hash=hash_api_key(raw_key, pepper=s.api_key_pepper),
            )
        )
    await ensure_default_card(tid)
    return tid, raw_key


def headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}
