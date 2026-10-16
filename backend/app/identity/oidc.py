"""SSO / OIDC token verification (Phase 6, build task 2).

Graduates the API-key skeleton to enterprise identity behind a seam. A bearer token that parses
as a JWT is verified here and mapped to a tenant principal; anything else stays an API key, so the
two coexist during a migration.

Modes (``AGENTOS_SSO_MODE``):

* ``none`` — SSO off. ``verify_token`` returns ``None`` (treat the bearer as an API key).
* ``mock`` — a hermetic, offline IdP: HS256 JWTs signed with ``AGENTOS_SSO_SECRET``. The
  ``agentos`` CLI / the dev SSO endpoint mint these so the full SSO path (login → scoped role →
  action) can be demoed and tested with no external IdP or network. This is the default enterprise
  story in dev, exactly like the mock payment gateway.
* ``oidc`` — a real issuer (Clerk/Auth0/Okta/Entra): RS256 JWTs verified against the issuer's JWKS
  (``AGENTOS_OIDC_JWKS_URL``), checking issuer + audience. The only mode that touches the network.

Claims we read: ``sub`` (subject), ``email``, ``tenant`` (or ``org`` — the tenant slug/id), and
``role`` (optional; defaults to the user's stored role or ``member``).
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt

from app.config.settings import Settings
from app.core.errors import AuthError
from app.core.logging import get_logger

log = get_logger(__name__)

_MOCK_ALG = "HS256"
_MOCK_ISSUER = "agentos-sso-mock"


@dataclass(frozen=True)
class SsoClaims:
    subject: str
    email: str | None
    tenant: str | None
    role: str | None


def looks_like_jwt(token: str) -> bool:
    """Three base64url segments split by dots; API keys are opaque ``ak_...`` tokens instead."""
    return token.count(".") == 2 and not token.startswith("ak_")


def mint_mock_token(
    settings: Settings,
    *,
    subject: str,
    email: str | None = None,
    tenant: str | None = None,
    role: str | None = None,
    ttl_seconds: int = 3600,
) -> str:
    """Mint an HS256 SSO token for the ``mock`` IdP (dev/test/demo only)."""
    import time

    now = int(time.time())
    payload = {
        "iss": _MOCK_ISSUER,
        "sub": subject,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if email is not None:
        payload["email"] = email
    if tenant is not None:
        payload["tenant"] = tenant
    if role is not None:
        payload["role"] = role
    return jwt.encode(payload, settings.sso_secret, algorithm=_MOCK_ALG)


def verify_token(token: str, settings: Settings) -> SsoClaims | None:
    """Verify an SSO JWT and return its claims, or ``None`` if SSO is off / the token isn't a JWT.

    Raises :class:`AuthError` when SSO is enabled and the token is a JWT but fails verification, so
    a forged/expired token is rejected rather than silently falling through to the API-key path.
    """
    if settings.sso_mode == "none" or not looks_like_jwt(token):
        return None
    if settings.sso_mode == "mock":
        claims = _verify_mock(token, settings)
    else:
        claims = _verify_oidc(token, settings)
    return SsoClaims(
        subject=str(claims.get("sub", "")),
        email=claims.get("email"),
        tenant=claims.get("tenant") or claims.get("org"),
        role=claims.get("role"),
    )


def _verify_mock(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(
            token,
            settings.sso_secret,
            algorithms=[_MOCK_ALG],
            issuer=_MOCK_ISSUER,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid SSO token: {exc}") from exc


def _verify_oidc(token: str, settings: Settings) -> dict:
    if not settings.oidc_jwks_url or not settings.oidc_issuer:
        raise AuthError("OIDC is not configured (issuer/jwks_url missing)")
    try:
        jwk_client = jwt.PyJWKClient(settings.oidc_jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid OIDC token: {exc}") from exc
