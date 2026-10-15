"""Request middleware: establish the trace id for every request.

The client may send its own id as ``X-Trace-Id`` (so a trace starts on the desktop and spans
client -> API -> worker). If absent, we mint one. It is echoed back in the response header and
threaded through logs/spans via the request context.
"""

from __future__ import annotations

from starlette.requests import Request

from app.core.context import set_trace_id

TRACE_HEADER = "x-trace-id"


async def trace_context_middleware(request: Request, call_next):
    incoming = request.headers.get(TRACE_HEADER)
    trace_id = set_trace_id(incoming)
    response = await call_next(request)
    response.headers[TRACE_HEADER] = trace_id
    return response
