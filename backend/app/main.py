"""FastAPI application factory.

One app, two deployment modes (Electron sidecar and cloud). Wiring order matters: observability
is configured before anything else (Phase 0 principle). The versioned API mounts under
``/v1`` with OpenAPI enabled so the client SDK can be generated from it.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app import __version__
from app.api.v1 import api_router
from app.bootstrap import ensure_schema, init_runtime
from app.config.settings import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import get_logger
from app.core.metrics import metrics_endpoint, metrics_middleware
from app.core.middleware import trace_context_middleware
from app.db.seed import seed_dev_tenant
from app.schemas.common import HealthResponse

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    init_runtime(settings)
    await ensure_schema(settings)
    await seed_dev_tenant(settings)
    log.info(
        "backend.startup",
        env=settings.env,
        database="sqlite" if settings.is_sqlite else "postgres",
        runtime="inprocess" if settings.use_inprocess_runtime else "arq",
    )
    yield
    from app.db.engine import dispose_engine

    await dispose_engine()
    log.info("backend.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Logging/tracing must exist before the app records anything.
    init_runtime(settings)

    app = FastAPI(
        title="AgentOS",
        version=__version__,
        description="AgentOS control plane — agent runtime, metering, and settlement.",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(trace_context_middleware)
    app.middleware("http")(metrics_middleware)
    install_error_handlers(app)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        return HealthResponse(
            service=settings.service_name,
            version=__version__,
            env=settings.env,
            database="sqlite" if settings.is_sqlite else "postgres",
            runtime="inprocess" if settings.use_inprocess_runtime else "arq",
            deployment_mode=settings.deployment_mode,
            region=settings.data_region,
        )

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return metrics_endpoint()

    app.include_router(api_router, prefix=settings.api_prefix)

    # Auto-instrument request spans (skip health/metrics to keep traces signal-rich).
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")

    return app


app = create_app()
