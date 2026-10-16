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
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
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


def tenant_fernet(
    master_secret: str, tenant_id: str, *, fallbacks: Sequence[str] = ()
) -> MultiFernet:
    """A ``MultiFernet`` that **encrypts** with the current secret and **decrypts** with any of
    the current + fallback secrets (Phase 6 key rotation, ADR-0008).

    Fernet encryption always uses the first key, so re-encrypting a token through this instance
    migrates it onto the current secret while ciphertext written under an older secret still
    decrypts — a zero-downtime master-key rotation with no schema change.
    """
    keys = [Fernet(_derive_key(master_secret, tenant_id))]
    keys.extend(Fernet(_derive_key(fb, tenant_id)) for fb in fallbacks)
    return MultiFernet(keys)


def encrypt_for_tenant(
    master_secret: str, tenant_id: str, plaintext: str, *, fallbacks: Sequence[str] = ()
) -> str:
    token = tenant_fernet(master_secret, tenant_id, fallbacks=fallbacks).encrypt(
        plaintext.encode("utf-8")
    )
    return token.decode("ascii")


def decrypt_for_tenant(
    master_secret: str, tenant_id: str, ciphertext: str, *, fallbacks: Sequence[str] = ()
) -> str:
    try:
        return (
            tenant_fernet(master_secret, tenant_id, fallbacks=fallbacks)
            .decrypt(ciphertext.encode("ascii"))
            .decode("utf-8")
        )
    except (InvalidToken, ValueError) as exc:
        raise CryptoError("credential ciphertext could not be decrypted") from exc


def rotate_ciphertext(
    master_secret: str, tenant_id: str, ciphertext: str, *, fallbacks: Sequence[str] = ()
) -> str:
    """Re-encrypt a token onto the current ``master_secret``, decrypting via a fallback if needed.

    Returns the new ciphertext (encrypted under the current secret). Raises ``CryptoError`` if the
    token cannot be decrypted with any known secret.
    """
    plaintext = decrypt_for_tenant(master_secret, tenant_id, ciphertext, fallbacks=fallbacks)
    return encrypt_for_tenant(master_secret, tenant_id, plaintext)
