"""CRM connector (DATA capability).

A minimal CRM modelled on a typical REST CRM (HubSpot/Salesforce-shaped), with read and write
split into separate scopes:

* ``crm.search_contacts`` — scope ``crm:read``   (look a customer up)
* ``crm.get_contact``     — scope ``crm:read``
* ``crm.create_ticket``   — scope ``crm:write``  (open a support ticket)

Deterministic offline: a tiny in-memory contact book keyed by a substring of the query, and a
ticket id derived from the input so results are stable across runs/replays. A live version
replaces the handlers with HTTP calls using ``credential.secret`` (API key / OAuth token) and
``credential.metadata['base_url']``.
"""

from __future__ import annotations

import hashlib

from app.connectors.base import ConnectorSpec, ResolvedCredential, ToolResult, ToolSpec
from app.connectors.builtin import BuiltinConnector
from app.connectors.capabilities import Capability

SCOPE_READ = "crm:read"
SCOPE_WRITE = "crm:write"

_CONTACTS = [
    {"id": "c_1001", "name": "Dana Customer", "email": "dana@example.com", "tier": "pro"},
    {"id": "c_1002", "name": "Sam Shopper", "email": "sam@example.com", "tier": "free"},
]

_TOOLS = (
    ToolSpec(
        name="crm.search_contacts",
        title="Search CRM contacts",
        description="Find contacts matching a query (name or email).",
        capability=Capability.DATA,
        required_scope=SCOPE_READ,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="crm.get_contact",
        title="Get a CRM contact",
        description="Fetch a single contact by id.",
        capability=Capability.DATA,
        required_scope=SCOPE_READ,
        input_schema={
            "type": "object",
            "properties": {"contact_id": {"type": "string"}},
            "required": ["contact_id"],
        },
    ),
    ToolSpec(
        name="crm.create_ticket",
        title="Create a CRM support ticket",
        description="Open a support ticket for a contact.",
        capability=Capability.DATA,
        required_scope=SCOPE_WRITE,
        input_schema={
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "contact_id": {"type": "string"},
            },
            "required": ["subject"],
        },
    ),
)


def _instance(cred: ResolvedCredential | None) -> str:
    return (cred.metadata.get("instance") if cred else None) or "dev-crm"


async def _search_contacts(args: dict, cred: ResolvedCredential | None) -> ToolResult:
    q = str(args.get("query", "")).lower()
    hits = [c for c in _CONTACTS if q and (q in c["name"].lower() or q in c["email"].lower())]
    if not hits:
        hits = _CONTACTS[:1]  # always ground on something, like kb_search
    return ToolResult(output={"instance": _instance(cred), "query": q, "results": hits})


async def _get_contact(args: dict, cred: ResolvedCredential | None) -> ToolResult:
    cid = str(args.get("contact_id", ""))
    match = next((c for c in _CONTACTS if c["id"] == cid), None)
    return ToolResult(
        output={"instance": _instance(cred), "contact": match}, is_error=match is None
    )


async def _create_ticket(args: dict, cred: ResolvedCredential | None) -> ToolResult:
    subject = str(args.get("subject", ""))
    # Deterministic id so a replayed step produces the same ticket (idempotent-friendly).
    digest = hashlib.sha256(f"{subject}".encode()).hexdigest()[:10]
    return ToolResult(
        output={
            "instance": _instance(cred),
            "ticket": {
                "id": f"t_{digest}",
                "subject": subject,
                "status": "open",
                "contact_id": args.get("contact_id"),
            },
        }
    )


SPEC = ConnectorSpec(
    key="crm",
    name="CRM",
    description="Look up customers and open support tickets in a CRM.",
    capabilities=(Capability.DATA,),
    auth_type="api_key",
    scopes=(SCOPE_READ, SCOPE_WRITE),
    tools=_TOOLS,
)


def build() -> BuiltinConnector:
    return BuiltinConnector(
        SPEC,
        {
            "crm.search_contacts": _search_contacts,
            "crm.get_contact": _get_contact,
            "crm.create_ticket": _create_ticket,
        },
    )
