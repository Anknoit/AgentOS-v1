"""Per-tenant secret encryption for the credential vault (ADR-0008).

Connector credentials (OAuth tokens, API keys) are the most dangerous data in the system, so
they are encrypted at rest with a key **derived per tenant** from the deployment master secret
(``AGENTOS_SECRET_KEY``). Deriving the key via HKDF with the ``tenant_id`` as salt means a
ciphertext stored for one tenant is cryptographically undecryptable with another tenant's key —
tenant isolation holds even if the RLS boundary were bypassed and rows leaked.

Fernet gives us authenticated symmetric encryption (AES-128-CBC + HMAC-SHA256) with a version
marker and timestamp, so tampering is detected on decrypt. ``MultiFernet`` leaves room to rotate
the master secret later (decrypt with old keys, re-encrypt with the new) without a schema change.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"agentos-credential-v1"


class CryptoError(Exception):
    """Raised when a ciphertext cannot be decrypted (wrong tenant, tampering, or key rotation)."""


def _derive_key(master_secret: str, tenant_id: str) -> bytes:
    """Derive a 32-byte Fernet key for a tenant from the master secret (HKDF-SHA256)."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=tenant_id.encode("utf-8"),
        info=_INFO,
    )
    return base64.urlsafe_b64encode(hkdf.derive(master_secret.encode("utf-8")))


def tenant_fernet(master_secret: str, tenant_id: str) -> Fernet:
    return Fernet(_derive_key(master_secret, tenant_id))


def encrypt_for_tenant(master_secret: str, tenant_id: str, plaintext: str) -> str:
    token = tenant_fernet(master_secret, tenant_id).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_for_tenant(master_secret: str, tenant_id: str, ciphertext: str) -> str:
    try:
        return (
            tenant_fernet(master_secret, tenant_id)
            .decrypt(ciphertext.encode("ascii"))
            .decode("utf-8")
        )
    except (InvalidToken, ValueError) as exc:
        raise CryptoError("credential ciphertext could not be decrypted") from exc
