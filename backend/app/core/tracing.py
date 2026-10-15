"""OpenTelemetry tracing.

One trace spans client -> API -> worker -> provider call. We:

* initialise a ``TracerProvider`` (console exporter in dev, OTLP when configured);
* auto-instrument FastAPI so every request is a span;
* expose ``start_span`` for runtime/worker spans;
* carry the W3C ``traceparent`` across the job boundary (see ``runtime.queue``) so a run
  executed on an Arq worker stays in the same trace as the request that enqueued it.

Our human-facing ``agentos.trace_id`` (used in logs) is attached as a span attribute so logs
and spans correlate even when reading the console exporter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.config.settings import Settings
from app.core.context import get_trace_id

_PROPAGATOR = TraceContextTextMapPropagator()
_INITIALISED = False


def configure_tracing(settings: Settings) -> None:
    global _INITIALISED
    if _INITIALISED:
        return

    resource = Resource.create(
        {"service.name": settings.service_name, "deployment.environment": settings.env}
    )
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter == "console":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    elif settings.otel_exporter == "otlp":
        # Imported lazily so the console path has no gRPC/HTTP exporter dependency at import.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    # "none" -> provider with no processors (no-op export, still creates spans/ids)

    trace.set_tracer_provider(provider)
    _INITIALISED = True


def get_tracer(name: str = "agentos"):
    return trace.get_tracer(name)


@contextmanager
def start_span(name: str, **attributes) -> Iterator[Span]:
    """Start a span as a child of the current context, tagging our human-facing trace id."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        tid = get_trace_id()
        if tid:
            span.set_attribute("agentos.trace_id", tid)
        for k, v in attributes.items():
            if v is not None:
                span.set_attribute(k, v)
        yield span


def inject_traceparent() -> dict[str, str]:
    """Serialise the current trace context to carry across a job/queue boundary."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier


@contextmanager
def attach_traceparent(carrier: dict[str, str] | None) -> Iterator[None]:
    """Re-attach a trace context extracted from a job payload (worker side)."""
    if not carrier:
        yield
        return
    ctx = _PROPAGATOR.extract(carrier)
    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)
