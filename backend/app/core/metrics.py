"""Prometheus metrics.

A tiny request-count + latency surface exposed at ``/metrics`` (scraped by Prometheus in the
obs compose profile). Runtime-specific metrics (runs, usage events) are added in later phases.
"""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS = Counter(
    "agentos_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "agentos_http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
RUNS_STARTED = Counter("agentos_runs_started_total", "Agent runs started")
USAGE_EVENTS = Counter("agentos_usage_events_total", "Usage events captured", ["event_type"])


async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    # Use the route template (not the raw path) to keep cardinality bounded.
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
    HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
    return response


def metrics_endpoint() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
