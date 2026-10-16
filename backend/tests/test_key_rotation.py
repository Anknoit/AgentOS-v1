"""Master-key rotation for the credential vault (Phase 6, build task 1 — ADR-0008).

Proves the zero-downtime rotation: ciphertext written under an old secret still decrypts while the
old secret is a fallback, ``rotate`` re-encrypts it under the new secret, and afterwards the old
secret can be dropped entirely with no loss of access.
"""

from __future__ import annotations

import pytest

from app.compliance.keyrotation import rotate_tenant_credentials
from app.config import get_settings
from app.core.crypto import CryptoError, decrypt_for_tenant, encrypt_for_tenant, rotate_ciphertext
from app.services import credentials as vault
from tests._helpers import new_tenant_with_key

OLD = "old-master-secret-aaaaaaaaaaaaaaaaaaaa"
NEW = "new-master-secret-bbbbbbbbbbbbbbbbbbbb"


def test_crypto_rotation_unit():
    tid = "t-crypto"
    token_old = encrypt_for_tenant(OLD, tid, "s3cret")
    # Old secret alone decrypts; new secret alone does not.
    assert decrypt_for_tenant(OLD, tid, token_old) == "s3cret"
    with pytest.raises(CryptoError):
        decrypt_for_tenant(NEW, tid, token_old)
    # New secret with the old as fallback decrypts, and rotate re-keys onto the new secret.
    assert decrypt_for_tenant(NEW, tid, token_old, fallbacks=[OLD]) == "s3cret"
    token_new = rotate_ciphertext(NEW, tid, token_old, fallbacks=[OLD])
    assert decrypt_for_tenant(NEW, tid, token_new) == "s3cret"  # no fallback needed anymore


@pytest.fixture()
def rotating_secrets():
    s = get_settings()
    prev_key, prev_fb = s.secret_key, s.secret_key_fallbacks
    s.secret_key = OLD
    s.secret_key_fallbacks = []
    yield s
    s.secret_key, s.secret_key_fallbacks = prev_key, prev_fb


@pytest.mark.asyncio
async def test_vault_survives_a_rotation(client, rotating_secrets):
    tid, _ = await new_tenant_with_key("rotate-vault")
    await vault.put_credential(tid, connector_key="slack", secret="xoxb-live")

    # Rotate the master secret: new primary, old moved to fallbacks. Still decrypts.
    rotating_secrets.secret_key = NEW
    rotating_secrets.secret_key_fallbacks = [OLD]
    resolved = await vault.resolve_credential(tid, "slack")
    assert resolved is not None and resolved.secret == "xoxb-live"

    # Re-encrypt the vault under the new secret, then drop the fallback entirely.
    n = await rotate_tenant_credentials(tid)
    assert n == 1
    rotating_secrets.secret_key_fallbacks = []
    resolved = await vault.resolve_credential(tid, "slack")
    assert resolved is not None and resolved.secret == "xoxb-live"
