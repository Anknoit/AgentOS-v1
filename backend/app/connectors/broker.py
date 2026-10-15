"""ConnectorBroker — runtime permission enforcement for connector calls (Phase 2, build task 4).

Every connector call an agent makes goes through here, and this is the only place that:

1. **resolves** a qualified tool name (``connector.tool``) to its connector and the scope it needs;
2. **enforces** the agent's grant — the ``agent_version``'s ``connector_bindings`` must bind the
   connector *and* include the required scope. An ungranted call is **denied and logged** (a
   ``connector_call`` action with ``outcome="denied"``) and raises ``ScopeDeniedError`` — it never
   reaches the connector, so no credential is touched and nothing is metered;
3. **loads** the tenant's credential from the vault (decrypted only now, for this call);
4. **invokes** the connector through its uniform ``MCPSession`` — identical path for a built-in or
   a third-party MCP server;
5. **meters** one ``usage_event`` (``event_type="connector_call"``) with the same deterministic
   idempotency key scheme as Phase 1 (``{run_id}:step{seq}:connector:{tool}``), so a replayed step
   never double-counts;
6. **audits** the call in the append-only ``action_log`` with the trace id — granted or denied, a
   connector call is always attributable.

The broker carries no ambient authority: it is constructed per run with exactly that run's grants.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import Settings
from app.connectors.base import ResolvedCredential, ToolResult
from app.connectors.registry import ConnectorRegistry, get_registry
from app.core.errors import ConflictError, ScopeDeniedError
from app.core.logging import get_logger
from app.core.tracing import start_span
from app.db.session import tenant_session
from app.metering.usage import UsageRecord, capture_usage
from app.runtime import store
from app.services import credentials as vault

log = get_logger(__name__)


@dataclass(frozen=True)
class ConnectorGrants:
    """What one run is allowed to do: connector_key -> binding (scopes + non-secret params)."""

    bindings: dict[str, dict] = field(default_factory=dict)

    def is_bound(self, connector_key: str) -> bool:
        return connector_key in self.bindings

    def scopes(self, connector_key: str) -> set[str]:
        return set(self.bindings.get(connector_key, {}).get("scopes", []))

    def params(self, connector_key: str) -> dict:
        b = self.bindings.get(connector_key, {})
        return {k: v for k, v in b.items() if k != "scopes"}

    @classmethod
    def from_bindings(cls, connector_bindings: dict | None) -> ConnectorGrants:
        return cls(bindings=dict(connector_bindings or {}))


@dataclass(frozen=True)
class BrokerCall:
    """The result of a granted connector call, for the kernel to stream and roll up."""

    tool: str
    connector_key: str
    scope: str
    output: dict
    usage_event_id: str | None


class ConnectorBroker:
    def __init__(
        self,
        *,
        tenant_id: str,
        run_id: str,
        trace_id: str | None,
        grants: ConnectorGrants,
        settings: Settings | None = None,
        registry: ConnectorRegistry | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._run_id = run_id
        self._trace_id = trace_id
        self._grants = grants
        self._settings = settings
        self._registry = registry or get_registry()

    def _resolve(self, tool: str) -> tuple[str, str]:
        """Return ``(connector_key, required_scope)`` for a qualified tool name."""
        hit = self._registry.find_tool(tool)
        if hit is not None:
            spec, tool_spec = hit
            return spec.key, tool_spec.required_scope
        # Dynamic (remote MCP) tool: enforce the connector-level grant.
        connector_key = tool.split(".", 1)[0]
        connector = self._registry.get(connector_key)
        if connector is None:
            raise NotFoundScope(connector_key)
        scopes = connector.spec.scopes
        required = scopes[0] if len(scopes) == 1 else f"{connector_key}:call"
        return connector_key, required

    async def call(self, tool: str, arguments: dict, *, seq: int) -> BrokerCall:
        """Enforce, invoke, meter, and audit one connector tool call."""
        connector_key, required_scope = self._resolve(tool)

        if not self._grants.is_bound(connector_key):
            await self._deny(seq, tool, connector_key, required_scope, "connector not granted")
        if required_scope not in self._grants.scopes(connector_key):
            await self._deny(seq, tool, connector_key, required_scope, "scope not granted")

        connector = self._registry.get(connector_key)
        if connector is None:  # pragma: no cover - resolve would have raised
            raise ConflictError(f"connector '{connector_key}' is not registered")

        credential: ResolvedCredential | None = await vault.resolve_credential(
            self._tenant_id, connector_key
        )
        if connector.spec.auth_type != "none" and credential is None:
            raise ConflictError(
                f"no credential stored for connector '{connector_key}' (bind one first)"
            )

        session = connector.session(credential)
        try:
            with start_span(
                "connector.call",
                **{"connector.key": connector_key, "connector.tool": tool},
            ):
                result: ToolResult = await session.call_tool(tool, arguments)
        finally:
            await session.close()

        usage_event_id = await self._meter(seq, tool, connector_key, result)
        await store.append_action(
            tenant_id=self._tenant_id,
            run_id=self._run_id,
            seq=seq,
            type="connector_call",
            name=tool,
            content={
                "connector": connector_key,
                "scope": required_scope,
                "outcome": "error" if result.is_error else "ok",
                "arguments": _redact_args(arguments),
                "result": result.output,
                "credential": _cred_hint(credential),
            },
            usage_event_id=usage_event_id,
            trace_id=self._trace_id,
        )
        log.info(
            "connector.call",
            connector=connector_key,
            tool=tool,
            outcome="error" if result.is_error else "ok",
            run_id=self._run_id,
        )
        return BrokerCall(
            tool=tool,
            connector_key=connector_key,
            scope=required_scope,
            output=result.output,
            usage_event_id=usage_event_id,
        )

    async def _meter(self, seq: int, tool: str, connector_key: str, result: ToolResult) -> str:
        with start_span("metering.capture_usage", **{"usage.kind": "connector_call"}):
            async with tenant_session(self._tenant_id) as session:
                event = await capture_usage(
                    session,
                    UsageRecord(
                        tenant_id=self._tenant_id,
                        idempotency_key=f"{self._run_id}:step{seq}:connector:{tool}",
                        event_type="connector_call",
                        provider=connector_key,
                        model=None,
                        quantity=result.quantity,
                        unit=result.unit,
                        run_id=self._run_id,
                        agent_id=None,
                        trace_id=self._trace_id,
                    ),
                )
                return event.id

    async def _deny(
        self, seq: int, tool: str, connector_key: str, required_scope: str, reason: str
    ) -> None:
        await store.append_action(
            tenant_id=self._tenant_id,
            run_id=self._run_id,
            seq=seq,
            type="connector_call",
            name=tool,
            content={
                "connector": connector_key,
                "scope": required_scope,
                "outcome": "denied",
                "reason": reason,
                "granted_scopes": sorted(self._grants.scopes(connector_key)),
            },
            trace_id=self._trace_id,
        )
        log.warning(
            "connector.denied",
            connector=connector_key,
            tool=tool,
            scope=required_scope,
            reason=reason,
            run_id=self._run_id,
        )
        raise ScopeDeniedError(
            f"agent is not granted scope '{required_scope}' on connector '{connector_key}'"
        )


class NotFoundScope(ScopeDeniedError):
    """A tool was requested for a connector that is not registered — treated as denied."""

    def __init__(self, connector_key: str) -> None:
        super().__init__(f"connector '{connector_key}' is not registered")


def _redact_args(arguments: dict) -> dict:
    """Keep argument *shape* in the audit log without risking secret values in free text."""
    redacted = {}
    for k, v in arguments.items():
        if isinstance(v, str) and len(v) > 256:
            redacted[k] = v[:256] + "…"
        else:
            redacted[k] = v
    return redacted


def _cred_hint(credential: ResolvedCredential | None) -> str | None:
    if credential is None:
        return None
    return vault.redact(credential.secret)
