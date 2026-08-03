"""FastAPI dependencies: authenticate the caller, then authorize the rank.

`current_user` is wired in as a *router-level* dependency in main.py rather
than decorated onto each endpoint. Per-endpoint opt-in means a new route added
next month is public until someone remembers the decorator; router-level means
a new route is protected by default and has to be deliberately exempted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.config import settings
from app.database import get_session
from app.models import User
from app.security import roles
from app.security.context import Actor, set_actor
from app.security.tokens import TokenError, decode_access_token

# auto_error=False so a missing header produces our own 401 with a WWW-Authenticate
# challenge rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentication required.",
    headers={"WWW-Authenticate": "Bearer"},
)


def client_ip(request: Request) -> str:
    """Best-effort client address.

    X-Forwarded-For is only consulted when TRUST_PROXY_HEADERS is on. Any client
    can send that header, so trusting it unconditionally would let an attacker
    write whatever address they like into the audit log — the one record that is
    supposed to be trustworthy.
    """
    if settings.TRUST_PROXY_HEADERS:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip", "")
        if real:
            return real.strip()
    return request.client.host if request.client else ""


def _reject(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def authenticate(token: str, session: Session) -> User:
    """Shared by the HTTP dependency and the WebSocket handshake."""
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise _reject(str(exc)) from exc

    user = session.get(User, claims.get("sub", ""))
    if not user or not user.active:
        # Same message either way — distinguishing "no such account" from
        # "disabled account" hands an attacker a user enumeration oracle.
        raise _reject("Session is no longer valid.")
    if claims.get("ver") != user.token_version:
        raise _reject("Session has been revoked. Please sign in again.")
    return user


async def current_user(request: Request,
                       creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                       session: Session = Depends(get_session)) -> User:
    """Authenticate the bearer token and publish the caller's identity.

    Declared `async` for a specific reason: FastAPI runs *sync* dependencies in
    a worker thread, and a ContextVar set inside that thread is discarded when
    it returns — the endpoint would then log an anonymous actor. An async
    dependency runs in the request's own task, and the endpoint (sync or async)
    inherits a copy of that context, so the attribution survives.
    """
    if creds is None or not creds.credentials:
        raise _UNAUTHENTICATED
    user = authenticate(creds.credentials, session)

    # Publish the identity for the audit log, and keep it on request.state so
    # error handlers and middleware can read it too.
    actor = Actor(id=user.id, username=user.username, role=user.role,
                  badge=user.badge_number, ip=client_ip(request),
                  user_agent=request.headers.get("user-agent", "")[:300])
    set_actor(actor)
    request.state.actor = actor
    request.state.user = user
    return user


def require(minimum: str) -> Callable[..., User]:
    """Dependency factory: caller must hold `minimum` rank or above."""
    if not roles.is_valid(minimum):
        raise ValueError(f"unknown role {minimum!r}")

    async def _guard(user: User = Depends(current_user)) -> User:
        if not roles.at_least(user.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {minimum} role.")
        return user

    _guard.__name__ = f"require_{minimum}"
    return _guard


require_analyst = require(roles.ANALYST)
require_supervisor = require(roles.SUPERVISOR)
require_admin = require(roles.ADMIN)


async def password_not_expired(user: User = Depends(current_user)) -> User:
    """Blocks normal work while a forced password change is outstanding.

    Applied to the routers, not to /auth/*, so the user can still reach the
    change-password endpoint to clear the flag.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before continuing.")
    return user


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
