"""Agent configuration service — create agents and mint immutable versions.

Deploying an agent from a template, or editing its config, both resolve to the same primitive:
write a new ``agent_version`` and advance the agent's ``current_version_id``. Versions are never
mutated, so a run that pins a version is always reproducible and a bad change rolls back by
pointing the agent at the previous version.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select

from app.core.errors import ConflictError, NotFoundError
from app.db.session import tenant_session
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.runtime import templates
from app.schemas.agent import AgentCreate, AgentUpdate, AgentVersionConfig


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "agent"


def _resolve_config(create: AgentCreate) -> AgentVersionConfig:
    if create.config is not None:
        return create.config
    if create.template:
        cfg = templates.template_config(create.template)
        if cfg is None:
            raise NotFoundError(f"unknown template '{create.template}'")
        return cfg
    return AgentVersionConfig()


async def _unique_slug(session, tenant_id: str, base: str) -> str:
    slug = base
    n = 1
    while True:
        exists = (
            await session.execute(
                select(Agent.id).where(Agent.tenant_id == tenant_id, Agent.slug == slug)
            )
        ).scalar_one_or_none()
        if exists is None:
            return slug
        n += 1
        slug = f"{base}-{n}"


async def create_agent(tenant_id: str, create: AgentCreate) -> Agent:
    config = _resolve_config(create)
    async with tenant_session(tenant_id) as session:
        slug = await _unique_slug(session, tenant_id, _slugify(create.name))
        agent = Agent(
            tenant_id=tenant_id,
            name=create.name,
            slug=slug,
            template=create.template,
            role=create.role,
            description=create.description,
            status="active",
        )
        session.add(agent)
        await session.flush()

        version = AgentVersion(
            tenant_id=tenant_id,
            agent_id=agent.id,
            version=1,
            model=config.model,
            system_prompt=config.system_prompt,
            tools=config.tools,
            guardrails=config.guardrails,
            knowledge=config.knowledge,
            connector_bindings=config.connector_bindings,
        )
        session.add(version)
        await session.flush()

        agent.current_version_id = version.id
    return agent


async def list_agents(tenant_id: str) -> list[Agent]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(Agent)
                .where(Agent.tenant_id == tenant_id)
                .order_by(Agent.created_at.desc())
            )
        ).scalars().all()
        return list(rows)


async def get_agent(tenant_id: str, agent_id: str) -> Agent:
    async with tenant_session(tenant_id) as session:
        agent = (
            await session.execute(
                select(Agent).where(Agent.tenant_id == tenant_id, Agent.id == agent_id)
            )
        ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"agent '{agent_id}' not found")
    return agent


async def list_versions(tenant_id: str, agent_id: str) -> list[AgentVersion]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(AgentVersion)
                .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent_id)
                .order_by(AgentVersion.version.desc())
            )
        ).scalars().all()
        return list(rows)


async def get_version(tenant_id: str, agent_version_id: str) -> AgentVersion:
    async with tenant_session(tenant_id) as session:
        version = (
            await session.execute(
                select(AgentVersion).where(
                    AgentVersion.tenant_id == tenant_id,
                    AgentVersion.id == agent_version_id,
                )
            )
        ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"agent version '{agent_version_id}' not found")
    return version


async def update_agent(tenant_id: str, agent_id: str, patch: AgentUpdate) -> Agent:
    async with tenant_session(tenant_id) as session:
        agent = (
            await session.execute(
                select(Agent).where(Agent.tenant_id == tenant_id, Agent.id == agent_id)
            )
        ).scalar_one_or_none()
        if agent is None:
            raise NotFoundError(f"agent '{agent_id}' not found")

        if patch.name is not None:
            agent.name = patch.name
        if patch.role is not None:
            agent.role = patch.role
        if patch.description is not None:
            agent.description = patch.description
        if patch.status is not None:
            agent.status = patch.status

        if patch.config is not None:
            next_version = (
                await session.execute(
                    select(func.coalesce(func.max(AgentVersion.version), 0)).where(
                        AgentVersion.tenant_id == tenant_id,
                        AgentVersion.agent_id == agent_id,
                    )
                )
            ).scalar_one() + 1
            version = AgentVersion(
                tenant_id=tenant_id,
                agent_id=agent_id,
                version=next_version,
                model=patch.config.model,
                system_prompt=patch.config.system_prompt,
                tools=patch.config.tools,
                guardrails=patch.config.guardrails,
                knowledge=patch.config.knowledge,
                connector_bindings=patch.config.connector_bindings,
            )
            session.add(version)
            await session.flush()
            agent.current_version_id = version.id
    return agent


async def resolve_current_version(tenant_id: str, agent: Agent) -> AgentVersion:
    if agent.current_version_id is None:
        raise ConflictError(f"agent '{agent.id}' has no current version")
    return await get_version(tenant_id, agent.current_version_id)
