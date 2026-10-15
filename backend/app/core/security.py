"""API-key hashing (ADR-0004).

API keys are shown once at creation and stored only as a salted+peppered hash. The stored form
is ``<prefix>.<sha256(pepper + key)>`` where ``prefix`` is the first 8 chars of the key, used to
narrow the lookup without widening the attack surface.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_api_key() -> str:
    """A URL-safe opaque key. Returned to the caller exactly once."""
    return "ak_" + secrets.token_urlsafe(32)


def key_prefix(raw_key: str) -> str:
    return raw_key[:8]


def hash_api_key(raw_key: str, *, pepper: str) -> str:
    digest = hashlib.sha256(f"{pepper}:{raw_key}".encode()).hexdigest()
    return f"{key_prefix(raw_key)}.{digest}"


def verify_api_key(raw_key: str, stored_hash: str, *, pepper: str) -> bool:
    return secrets.compare_digest(hash_api_key(raw_key, pepper=pepper), stored_hash)
