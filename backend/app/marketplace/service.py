"""Publish / discover / install marketplace listings.

The marketplace is the one **cross-tenant** surface, so every read/write here goes through
``system_session`` (never ``tenant_session``) — the listing table is deliberately outside RLS.
Writes still carry ``publisher_tenant_id`` for attribution, and installs write into the *caller's*
tenant through the normal tenant-scoped services, so the isolation boundary holds for everything
except the shared catalogue itself.

**No secrets ever cross the marketplace.** Publishing an agent copies its immutable version config
(model/prompt/tools/guardrails/connector *bindings* — scopes, not credentials). Publishing a
connector copies only non-secret ``provider_meta`` (e.g. an MCP server URL). Installing recreates
the agent/binding in the installer's tenant; the installer must then store their own credentials.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select

from app.core.errors import NotFoundError, ValidationError
from app.db.session import system_session
from app.models.marketplace_listing import MarketplaceListing
from app.schemas.agent import AgentCreate, AgentVersionConfig
from app.services import agents as agents_service

AGENT_TEMPLATE = "agent_template"
CONNECTOR = "connector"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "listing"


async def _unique_slug(session, base: str) -> str:
    slug, n = base, 1
    while True:
        exists = (
            await session.execute(
                select(MarketplaceListing.id).where(MarketplaceListing.slug == slug)
            )
        ).scalar_one_or_none()
        if exists is None:
            return slug
        n += 1
        slug = f"{base}-{n}"


async def publish_agent(
    tenant_id: str, agent_id: str, *, name: str | None = None, description: str | None = None
) -> MarketplaceListing:
    """Publish an agent's current version config as an installable template."""
    agent = await agents_service.get_agent(tenant_id, agent_id)
    version = await agents_service.resolve_current_version(tenant_id, agent)
    config = AgentVersionConfig(
        model=version.model,
        system_prompt=version.system_prompt,
        tools=list(version.tools or []),
        guardrails=dict(version.guardrails or {}),
        knowledge=list(version.knowledge or []),
        connector_bindings=dict(version.connector_bindings or {}),
    )
    async with system_session() as session:
        slug = await _unique_slug(session, _slugify(name or agent.name))
        listing = MarketplaceListing(
            publisher_tenant_id=tenant_id,
            kind=AGENT_TEMPLATE,
            slug=slug,
            name=name or agent.name,
            description=description or agent.description,
            config=config.model_dump(),
        )
        session.add(listing)
        await session.flush()
        await session.refresh(listing)
        return listing


async def publish_connector(
    tenant_id: str,
    *,
    connector_key: str,
    name: str,
    description: str | None = None,
    provider_meta: dict | None = None,
) -> MarketplaceListing:
    """Publish a connector configuration (non-secret ``provider_meta`` only)."""
    async with system_session() as session:
        slug = await _unique_slug(session, _slugify(name))
        listing = MarketplaceListing(
            publisher_tenant_id=tenant_id,
            kind=CONNECTOR,
            slug=slug,
            name=name,
            description=description,
            config={"connector_key": connector_key, "provider_meta": provider_meta or {}},
        )
        session.add(listing)
        await session.flush()
        await session.refresh(listing)
        return listing


async def list_listings(*, kind: str | None = None) -> list[MarketplaceListing]:
    async with system_session() as session:
        stmt = (
            select(MarketplaceListing)
            .where(MarketplaceListing.published.is_(True))
            .order_by(MarketplaceListing.installs.desc(), MarketplaceListing.created_at.desc())
        )
        if kind:
            stmt = stmt.where(MarketplaceListing.kind == kind)
        return list((await session.execute(stmt)).scalars().all())


async def get_listing(listing_id: str) -> MarketplaceListing:
    async with system_session() as session:
        listing = (
            await session.execute(
                select(MarketplaceListing).where(MarketplaceListing.id == listing_id)
            )
        ).scalar_one_or_none()
    if listing is None:
        raise NotFoundError(f"listing '{listing_id}' not found")
    return listing


async def _bump_installs(listing_id: str) -> None:
    async with system_session() as session:
        await session.execute(
            MarketplaceListing.__table__.update()
            .where(MarketplaceListing.id == listing_id)
            .values(installs=func.coalesce(MarketplaceListing.installs, 0) + 1)
        )


async def install(tenant_id: str, listing_id: str, *, name: str | None = None) -> dict:
    """Install a listing into ``tenant_id``.

    For an agent template this creates a new agent (from the published config) in the caller's
    tenant and returns ``{"kind","agent_id"}``. For a connector it returns the config the caller
    needs to store a credential for (``{"kind","connector_key","provider_meta"}``). Either way the
    install counter is bumped; no publisher data is exposed beyond the listing itself.
    """
    listing = await get_listing(listing_id)
    if listing.kind == AGENT_TEMPLATE:
        config = AgentVersionConfig.model_validate(listing.config)
        agent = await agents_service.create_agent(
            tenant_id,
            AgentCreate(
                name=name or listing.name,
                role="marketplace",
                description=f"Installed from marketplace listing '{listing.slug}'",
                config=config,
            ),
        )
        await _bump_installs(listing.id)
        return {"kind": listing.kind, "agent_id": agent.id, "slug": listing.slug}
    if listing.kind == CONNECTOR:
        await _bump_installs(listing.id)
        return {
            "kind": listing.kind,
            "connector_key": listing.config.get("connector_key"),
            "provider_meta": listing.config.get("provider_meta", {}),
            "slug": listing.slug,
            "note": "store your own credential for this connector to use it",
        }
    raise ValidationError(f"listing '{listing_id}' has unknown kind '{listing.kind}'")
