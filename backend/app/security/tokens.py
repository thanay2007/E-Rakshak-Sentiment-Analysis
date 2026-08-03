"""JWT issue and verify.

Deliberate choices:

  • The decode call pins `algorithms=["HS256"]`. Accepting whatever the token's
    own header asks for is the classic JWT break (`alg: none`, or RS256→HS256
    confusion) — the verifier, not the token, decides the algorithm.
  • `ver` carries the user's `token_version`. Deactivating a user or forcing a
    logout bumps that column, and every token already in the wild stops
    verifying on the next request. Without it, revocation would only take
    effect whenever the token happened to expire.
  • No secret is ever hardcoded or defaulted to a fixed string. If SECRET_KEY
    is unset the process generates a random one at boot: existing sessions
    break on every restart, which is noisy and annoying and therefore gets
    fixed — the failure mode is a nuisance, not a silent forgery hole.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

log = logging.getLogger("sentinel.auth")

_ALGORITHM = "HS256"
_ISSUER = "sentinel"


def _secret() -> str:
    global _EPHEMERAL
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    if _EPHEMERAL is None:
        _EPHEMERAL = secrets.token_urlsafe(48)
        log.warning(
            "SECRET_KEY is not set — generated a random one for this process. "
            "All sessions will be invalidated on restart and the app CANNOT be "
            "run on more than one worker. Set SECRET_KEY in backend/.env before "
            "deploying: python -c \"import secrets;print(secrets.token_urlsafe(48))\"")
    return _EPHEMERAL


_EPHEMERAL: str | None = None


class TokenError(Exception):
    """Token missing, malformed, expired or revoked."""


def issue_access_token(*, user_id: str, username: str, role: str,
                       token_version: int) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    ttl = timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
    now = datetime.now(timezone.utc)
    payload = {
        "iss": _ISSUER,
        "sub": user_id,
        "usr": username,
        "rol": role,
        "ver": token_version,
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict:
    """Verified claims, or TokenError. Never raises anything else."""
    try:
        return jwt.decode(
            token, _secret(), algorithms=[_ALGORITHM], issuer=_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Session expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid session token.") from exc
