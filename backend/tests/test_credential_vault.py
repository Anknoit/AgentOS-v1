"""Credential vault: secrets encrypted per tenant, never returned, isolated cryptographically."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.crypto import (
    CryptoError,
    decrypt_for_tenant,
    encrypt_for_tenant,
)
from app.db.session import system_session, tenant_session
from app.models.credential import Credential
from app.models.tenant import Tenant
from app.services import credentials as vault


async def _tenant_id() -> str:
    async with system_session() as s:
        return (await s.execute(select(Tenant).limit(1))).scalar_one().id


# --- pure crypto layer: per-tenant isolation ---

def test_crypto_roundtrip_and_tenant_isolation():
    master = "unit-test-master-secret"
    ct = encrypt_for_tenant(master, "tenant-a", "super-secret-token")
    assert "super-secret-token" not in ct  # not stored in plaintext
    assert decrypt_for_tenant(master, "tenant-a", ct) == "super-secret-token"
    # another tenant's derived key cannot read tenant-a's ciphertext
    with pytest.raises(CryptoError):
        decrypt_for_tenant(master, "tenant-b", ct)


# --- vault service over the DB ---

@pytest.mark.asyncio
async def test_put_credential_encrypts_at_rest_and_resolves(client):
    tid = await _tenant_id()
    await vault.put_credential(
        tid,
        connector_key="slack",
        secret="xoxb-the-real-token",
        provider_meta={"workspace": "acme"},
        scopes=["chat:write"],
    )
    # stored ciphertext must not contain the plaintext secret
    async with tenant_session(tid) as s:
        row = (
            await s.execute(select(Credential).where(Credential.connector_key == "slack"))
        ).scalar_one()
    assert "xoxb-the-real-token" not in row.ciphertext

    # the vault decrypts it back for use at call time
    resolved = await vault.resolve_credential(tid, "slack")
    assert resolved is not None
    assert resolved.secret == "xoxb-the-real-token"
    assert resolved.metadata["workspace"] == "acme"


@pytest.mark.asyncio
async def test_credential_api_never_returns_secret(client, auth_headers):
    r = client.post(
        "/v1/credentials",
        headers=auth_headers,
        json={
            "connector_key": "crm",
            "secret": "crm-api-key-123",
            "provider_meta": {"instance": "acme-crm"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "secret" not in body and "ciphertext" not in body
    assert body["connector_key"] == "crm"

    listed = client.get("/v1/credentials", headers=auth_headers).json()
    assert any(c["connector_key"] == "crm" for c in listed)
    assert all("secret" not in c and "ciphertext" not in c for c in listed)


@pytest.mark.asyncio
async def test_credential_delete(client, auth_headers):
    client.post(
        "/v1/credentials",
        headers=auth_headers,
        json={"connector_key": "http", "name": "scratch", "secret": "k"},
    )
    d = client.delete("/v1/credentials/http?name=scratch", headers=auth_headers)
    assert d.status_code == 204
    listed = client.get("/v1/credentials", headers=auth_headers).json()
    assert not any(c["connector_key"] == "http" and c["name"] == "scratch" for c in listed)


def test_put_credential_unknown_connector_404(client, auth_headers):
    r = client.post(
        "/v1/credentials",
        headers=auth_headers,
        json={"connector_key": "does-not-exist", "secret": "k"},
    )
    assert r.status_code == 404
