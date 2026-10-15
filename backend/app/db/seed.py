"""Dev bootstrap data.

When ``AGENTOS_SEED_DEV_TENANT`` is on and the DB has no tenants, seed one tenant + user +
API key so the Electron client (and tests) can authenticate immediately. The key hash is
derived from ``AGENTOS_DEV_API_KEY`` so the plaintext is known in dev.
"""

from __future__ import annotations

from sqlalchemy import select

from app.config.settings import Settings
from app.core.logging import get_logger
from app.core.security import hash_api_key, key_prefix
from app.db.session import system_session
from app.models.api_key import ApiKey
from app.models.tenant import Tenant
from app.models.user import User

log = get_logger(__name__)


async def seed_dev_tenant(settings: Settings) -> None:
    if not settings.seed_dev_tenant:
        return
    tenant_id: str | None = None
    async with system_session() as session:
        existing = (await session.execute(select(Tenant).limit(1))).scalar_one_or_none()
        if existing is not None:
            return

        tenant = Tenant(slug=settings.dev_tenant_slug, name="Dev Tenant")
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

        user = User(tenant_id=tenant.id, email=settings.dev_user_email, role="owner")
        session.add(user)
        await session.flush()

        key = ApiKey(
            tenant_id=tenant.id,
            user_id=user.id,
            name="dev",
            prefix=key_prefix(settings.dev_api_key),
            key_hash=hash_api_key(settings.dev_api_key, pepper=settings.api_key_pepper),
        )
        session.add(key)

    # Seed the default rate card so the tenant has active pricing from the first run (Phase 3).
    # Done in a tenant-scoped session so Postgres RLS accepts the write.
    if tenant_id is not None:
        from app.services.ratecards import ensure_default_card

        await ensure_default_card(tenant_id)

    log.info(
        "seed.dev_tenant",
        tenant=settings.dev_tenant_slug,
        api_key=settings.dev_api_key,
        hint="use this key as 'Authorization: Bearer <key>'",
    )
