"""Application error types and a uniform error envelope.

Every error response is ``{"error": {"code", "message", "trace_id"}}`` so the client can show
a stable code and the trace id for support.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_trace_id


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class AuthError(AppError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class ScopeDeniedError(ForbiddenError):
    """A connector call demanded a scope the agent's version was not granted (Phase 2).

    Raised by the ConnectorBroker at call time and recorded in the action log, so an
    ungranted capability is both denied and attributable.
    """

    code = "scope_denied"


class BudgetExceededError(AppError):
    """A billable action was refused because a hard spend cap (or prepaid balance) is exhausted.

    Raised by the credit controller *before* the action runs (online credit control, Phase 3), so
    an agent stops at its limit rather than overrunning it. The kernel catches it and finalizes the
    run as ``stopped`` with the reason; if surfaced over HTTP it maps to 402 Payment Required.
    """

    status_code = 402
    code = "budget_exceeded"


class PaymentError(AppError):
    """A settlement operation failed — a bad/forged gateway signature or an invalid top-up/refund.

    Raised by the billing layer (Phase 4). Distinct from ``BudgetExceededError`` (spend control):
    this is about money movement through the gateway, and maps to 400 so a forged webhook or a
    tampered checkout callback is rejected without crediting a wallet.
    """

    status_code = 400
    code = "payment_error"


class VelocityError(AppError):
    """A tenant exceeded a fraud velocity limit (too many runs / top-ups in a window — Phase 6).

    Maps to 429 Too Many Requests. Tripping a limit also places a hold, so the next billable
    action is refused with ``TenantHeldError`` until an operator releases it.
    """

    status_code = 429
    code = "velocity_exceeded"


class TenantHeldError(ForbiddenError):
    """Billable work is refused because the tenant is under a fraud/abuse hold (Phase 6).

    Raised before a run is dispatched or a top-up is confirmed. An operator clears it via
    ``POST /v1/admin/holds/{id}/release``; maps to 403.
    """

    code = "tenant_held"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    """A request was well-formed but semantically invalid (e.g. an unknown RBAC role)."""

    status_code = 422
    code = "validation_error"


def _envelope(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "trace_id": get_trace_id()}},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return _envelope(exc.code, exc.message, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        return _envelope(code, str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        return _envelope("validation_error", "Request validation failed", 422)
