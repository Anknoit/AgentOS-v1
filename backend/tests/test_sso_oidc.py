"""SSO / OIDC (Phase 6, build task 2) — a member logs in with a token, not an API key.

Uses the hermetic ``mock`` IdP (HS256 signed with the SSO secret), the offline analogue of a real
OIDC issuer. Proves the full SSO path: mint → present as Bearer → resolve to tenant + role, that a
role claim drives RBAC over SSO, and that a forged/expired token is rejected (not silently treated
as an API key).
"""

from __future__ import annotations

import jwt
import pytest

from app.config import get_settings
from app.identity.oidc import mint_mock_token
from tests._helpers import headers, new_tenant_with_key


@pytest.fixture()
def sso_mock():
    s = get_settings()
    prev = s.sso_mode
    s.sso_mode = "mock"
    yield s
    s.sso_mode = prev


@pytest.mark.asyncio
async def test_sso_login_resolves_tenant_and_role(client, sso_mock):
    tid, _ = await new_tenant_with_key("sso-login")
    token = mint_mock_token(sso_mock, subject="u-1", email="sso-login@t.local", tenant=tid)

    r = client.get("/v1/whoami", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == tid
    assert body["auth_method"] == "sso"
    # Role inherited from the member row (owner) since the token carried no role claim.
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_sso_role_claim_gates_writes(client, sso_mock):
    tid, _ = await new_tenant_with_key("sso-rbac")
    token = mint_mock_token(
        sso_mock, subject="u-2", email="sso-rbac@t.local", tenant=tid, role="auditor"
    )
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/agents", headers=h).status_code == 200
    assert client.post("/v1/agents", headers=h, json={"name": "No"}).status_code == 403


@pytest.mark.asyncio
async def test_forged_sso_token_is_rejected(client, sso_mock):
    tid, _ = await new_tenant_with_key("sso-forged")
    forged = jwt.encode(
        {"iss": "agentos-sso-mock", "sub": "x", "tenant": tid, "exp": 9999999999},
        "the-wrong-secret-but-long-enough-to-avoid-a-warning",
        algorithm="HS256",
    )
    r = client.get("/v1/whoami", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


@pytest.mark.asyncio
async def test_mint_endpoint_requires_mock_mode(client, auth_headers):
    # Default sso_mode is "none": minting is refused.
    assert get_settings().sso_mode == "none"
    r = client.post("/v1/auth/sso/token", headers=auth_headers, json={"subject": "u"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_api_keys_still_work_alongside_sso(client, sso_mock):
    # With SSO on, an opaque API key is still resolved the old way.
    tid, key = await new_tenant_with_key("sso-coexist")
    r = client.get("/v1/whoami", headers=headers(key))
    assert r.status_code == 200
    assert r.json()["auth_method"] == "api_key"
