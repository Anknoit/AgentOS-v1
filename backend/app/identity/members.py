"""Member + API-key management (Phase 6, build task 2).

Granular roles over the fleet start with *who is in the tenant*. A member is a ``user`` row with an
RBAC role; an API key is a bearer credential that also carries a role (so a tenant can mint a
read-only auditor key or a CI key scoped to runs). Both are identity tables, so they are read/
written through ``system_session`` scoped explicitly by ``tenant_id`` — the same path the auth
lookup and dev seed use.

Secrets rule: an API key's plaintext is returned **exactly once**, at creation; only its salted +
peppered hash is stored (``core.security``).
"""

from __future__ import annotations

from sqlalchemy import select

from app.config.settings import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import generate_api_key, hash_api_key, key_prefix
from app.db.session import system_session
from app.identity.rbac import VALID_ROLES
from app.models.api_key import ApiKey
from app.models.user import User


def _check_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValidationError(
            f"unknown role '{role}' (valid: {', '.join(sorted(VALID_ROLES))})"
        )


async def list_members(tenant_id: str) -> list[User]:
    async with system_session() as session:
        rows = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
            )
        ).scalars().all()
        return list(rows)


async def create_member(tenant_id: str, *, email: str, role: str = "member") -> User:
    _check_role(role)
    async with system_session() as session:
        existing = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.email == email)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"member '{email}' already exists")
        user = User(tenant_id=tenant_id, email=email, role=role)
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user


async def update_member_role(tenant_id: str, user_id: str, *, role: str) -> User:
    _check_role(role)
    async with system_session() as session:
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.id == user_id)
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError(f"member '{user_id}' not found")
        user.role = role
        await session.flush()
        await session.refresh(user)
        return user


async def delete_member(tenant_id: str, user_id: str) -> None:
    async with system_session() as session:
        user = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.id == user_id)
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError(f"member '{user_id}' not found")
        await session.delete(user)


async def list_api_keys(tenant_id: str) -> list[ApiKey]:
    async with system_session() as session:
        rows = (
            await session.execute(
                select(ApiKey)
                .where(ApiKey.tenant_id == tenant_id)
                .order_by(ApiKey.created_at)
            )
        ).scalars().all()
        return list(rows)


async def create_api_key(
    tenant_id: str, *, name: str = "default", role: str = "owner", user_id: str | None = None
) -> tuple[ApiKey, str]:
    """Mint a scoped API key. Returns ``(row, plaintext)`` — the plaintext is shown only here."""
    _check_role(role)
    settings = get_settings()
    raw = generate_api_key()
    async with system_session() as session:
        key = ApiKey(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            role=role,
            prefix=key_prefix(raw),
            key_hash=hash_api_key(raw, pepper=settings.api_key_pepper),
        )
        session.add(key)
        await session.flush()
        await session.refresh(key)
        return key, raw


async def revoke_api_key(tenant_id: str, key_id: str) -> None:
    async with system_session() as session:
        key = (
            await session.execute(
                select(ApiKey).where(ApiKey.tenant_id == tenant_id, ApiKey.id == key_id)
            )
        ).scalar_one_or_none()
        if key is None:
            raise NotFoundError(f"api key '{key_id}' not found")
        key.revoked = True
