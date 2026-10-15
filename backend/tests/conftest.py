"""Test fixtures.

Everything runs on the SQLite dev-fallback in a temp file with the mock LLM provider — no
Postgres, Redis, or network. Env is set before any app module imports so the cached settings
pick it up.
"""

from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="agentos-test-")
os.environ.update(
    {
        "AGENTOS_ENV": "test",
        "AGENTOS_DATABASE_URL": f"sqlite+aiosqlite:///{_tmp}/test.db",
        "AGENTOS_LLM_PROVIDER": "mock",
        "AGENTOS_OTEL_EXPORTER": "none",
        "AGENTOS_SEED_DEV_TENANT": "true",
        "AGENTOS_DEV_API_KEY": "test-key",
        "AGENTOS_LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402

API_KEY = "test-key"


@pytest.fixture(scope="session")
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture()
def client(settings):
    from app.main import create_app

    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}
