"""Master-key rotation for the credential vault (Phase 6, build task 1 — ADR-0008).

Rotating ``AGENTOS_SECRET_KEY`` is a two-step, zero-downtime operation:

1. Set the new secret as ``secret_key`` and move the old one into ``secret_key_fallbacks``. Every
   credential still decrypts (``MultiFernet`` tries the fallback), so the system keeps working.
2. Run ``rotate_tenant_credentials`` (``agentos rotate-keys``): each stored ciphertext is decrypted
   with whichever key works and **re-encrypted under the current secret**. Once every tenant is
   rotated, the old secret can be dropped from the fallbacks.

Only the ciphertext changes — no schema migration, no plaintext ever written to disk.
"""

from __future__ import annotations

from sqlalchemy import select

from app.config.settings import get_settings
from app.core.crypto import rotate_ciphertext
from app.core.logging import get_logger
from app.db.session import system_session, tenant_session
from app.models.credential import Credential
from app.models.tenant import Tenant

log = get_logger(__name__)


async def rotate_tenant_credentials(tenant_id: str) -> int:
    """Re-encrypt every credential of one tenant under the current master secret. Returns count."""
    settings = get_settings()
    rotated = 0
    async with tenant_session(tenant_id) as session:
        creds = (
            await session.execute(
                select(Credential).where(Credential.tenant_id == tenant_id)
            )
        ).scalars().all()
        for cred in creds:
            cred.ciphertext = rotate_ciphertext(
                settings.secret_key,
                tenant_id,
                cred.ciphertext,
                fallbacks=settings.secret_key_fallbacks,
            )
            rotated += 1
    log.info("keys.rotated", tenant_id=tenant_id, credentials=rotated)
    return rotated


async def rotate_all_credentials() -> dict[str, int]:
    """Rotate every tenant's credentials. Returns ``{tenant_id: count}``."""
    async with system_session() as session:
        tenant_ids = list((await session.execute(select(Tenant.id))).scalars().all())
    return {tid: await rotate_tenant_credentials(tid) for tid in tenant_ids}
