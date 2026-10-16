"""Request-scoped context.

One ``trace_id`` and one tenant context follow a unit of work from the client through the API
into the worker. They live in ``contextvars`` so logging, tracing, and the DB session can all
read them without threading them through every call. The worker re-seeds these from the job
payload so the same trace spans client -> API -> worker.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)


@dataclass(frozen=True)
class TenantContext:
    """The authenticated principal for the current unit of work.

    ``role`` drives RBAC (Phase 6): it is the role of the user/key that authenticated, and the
    ``Scoped`` dependency checks it against the permission a write endpoint demands.
    ``auth_method`` records how the principal proved itself (``api_key`` / ``sso``) for the audit.
    """

    tenant_id: str
    user_id: str | None = None
    role: str = "owner"
    auth_method: str = "api_key"


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace_id(trace_id: str | None) -> str:
    tid = trace_id or new_trace_id()
    _trace_id.set(tid)
    return tid


def get_trace_id() -> str | None:
    return _trace_id.get()


def set_tenant(ctx: TenantContext | None) -> None:
    _tenant_id.set(ctx.tenant_id if ctx else None)
    _user_id.set(ctx.user_id if ctx else None)


def get_tenant_id() -> str | None:
    return _tenant_id.get()


def get_user_id() -> str | None:
    return _user_id.get()


def current_tenant() -> TenantContext | None:
    tid = _tenant_id.get()
    if tid is None:
        return None
    return TenantContext(tenant_id=tid, user_id=_user_id.get())
