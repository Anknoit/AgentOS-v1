"""Credential vault service (Phase 2, build task 3).

The single place connector secrets are written and read. Secrets are encrypted **before** they
touch the database (per-tenant key, ADR-0008) and decrypted **only** here, at call time, into a
transient ``ResolvedCredential`` the broker hands to a connector. The secret is never returned by
any API, never logged, and never stored in plaintext.

OAuth and API-key flows share this storage: an API key is stored as the secret directly; an OAuth
flow stores the access token (and optionally a refresh token in ``provider_meta`` — also inside
the ciphertext for refresh tokens) with ``expires_at`` so a future refresh seam can rotate it
without re-consent. Short-lived tokens are preferred; ``expires_at`` lets the broker refuse an
expired credential rather than call with a stale token.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.config.settings import get_settings
from app.connectors.base import ResolvedCredential
from app.connectors.registry import get_registry
from app.core.crypto import decrypt_for_tenant, encrypt_for_tenant
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models.credential import Credential

log = get_logger(__name__)


async def put_credential(
    tenant_id: str,
    *,
    connector_key: str,
    secret: str,
    name: str = "default",
    provider_meta: dict | None = None,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> Credential:
    """Create or replace a tenant's credential for a connector. The secret is encrypted at rest."""
    registry = get_registry()
    connector = registry.get(connector_key)
    if connector is None:
        raise NotFoundError(f"unknown connector '{connector_key}'")

    settings = get_settings()
    ciphertext = encrypt_for_tenant(settings.secret_key, tenant_id, secret)

    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                select(Credential).where(
                    Credential.tenant_id == tenant_id,
                    Credential.connector_key == connector_key,
                    Credential.name == name,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.ciphertext = ciphertext
            existing.auth_type = connector.spec.auth_type
            existing.provider_meta = provider_meta or {}
            existing.scopes = scopes or []
            existing.expires_at = expires_at
            cred = existing
        else:
            cred = Credential(
                tenant_id=tenant_id,
                connector_key=connector_key,
                name=name,
                auth_type=connector.spec.auth_type,
                ciphertext=ciphertext,
                provider_meta=provider_meta or {},
                scopes=scopes or [],
                expires_at=expires_at,
            )
            session.add(cred)
        await session.flush()
    log.info("credential.stored", connector=connector_key, name=name, tenant_id=tenant_id)
    return cred


async def list_credentials(tenant_id: str) -> list[Credential]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(Credential)
                .where(Credential.tenant_id == tenant_id)
                .order_by(Credential.connector_key, Credential.name)
            )
        ).scalars().all()
        return list(rows)


async def delete_credential(tenant_id: str, connector_key: str, name: str = "default") -> None:
    async with tenant_session(tenant_id) as session:
        cred = (
            await session.execute(
                select(Credential).where(
                    Credential.tenant_id == tenant_id,
                    Credential.connector_key == connector_key,
                    Credential.name == name,
                )
            )
        ).scalar_one_or_none()
        if cred is None:
            raise NotFoundError(f"no '{name}' credential for connector '{connector_key}'")
        await session.delete(cred)


async def resolve_credential(
    tenant_id: str, connector_key: str, name: str = "default"
) -> ResolvedCredential | None:
    """Decrypt a credential for use at call time. Returns None if none is stored.

    Refuses an expired credential (raises ``ConflictError``) so a stale token never reaches a
    connector.
    """
    async with tenant_session(tenant_id) as session:
        cred = (
            await session.execute(
                select(Credential).where(
                    Credential.tenant_id == tenant_id,
                    Credential.connector_key == connector_key,
                    Credential.name == name,
                )
            )
        ).scalar_one_or_none()
        if cred is None:
            return None
        if cred.expires_at is not None and cred.expires_at < datetime.now(timezone.utc):
            raise ConflictError(f"credential for '{connector_key}' has expired")
        settings = get_settings()
        secret = decrypt_for_tenant(settings.secret_key, tenant_id, cred.ciphertext)
        return ResolvedCredential(
            connector_key=connector_key,
            auth_type=cred.auth_type,
            secret=secret,
            metadata=dict(cred.provider_meta or {}),
        )


def redact(secret: str) -> str:
    """A non-reversible hint for logs/UI — never the secret itself."""
    if not secret:
        return ""
    tail = secret[-4:] if len(secret) >= 8 else ""
    return f"••••{tail}"
