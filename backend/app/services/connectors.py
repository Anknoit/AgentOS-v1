"""Connector discovery service (Phase 2).

Read-only views over the registry for the API. Discovery is tenant-agnostic (the *catalogue* of
connectors is the same for everyone); what differs per tenant is which credentials are stored and
what an agent_version is granted.
"""

from __future__ import annotations

from app.connectors.base import ConnectorSpec
from app.connectors.registry import get_registry
from app.core.errors import NotFoundError
from app.schemas.connector import ConnectorOut, ToolOut


def _to_out(spec: ConnectorSpec) -> ConnectorOut:
    return ConnectorOut(
        key=spec.key,
        name=spec.name,
        description=spec.description,
        capabilities=[c.value for c in spec.capabilities],
        auth_type=spec.auth_type,
        scopes=list(spec.scopes),
        transport=spec.transport,
        tools=[
            ToolOut(
                name=t.name,
                title=t.title,
                description=t.description,
                capability=t.capability.value,
                scope=t.required_scope,
                input_schema=t.input_schema,
            )
            for t in spec.tools
        ],
    )


def list_connectors() -> list[ConnectorOut]:
    return [_to_out(s) for s in get_registry().specs()]


def get_connector(key: str) -> ConnectorOut:
    connector = get_registry().get(key)
    if connector is None:
        raise NotFoundError(f"unknown connector '{key}'")
    return _to_out(connector.spec)
