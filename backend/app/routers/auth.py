"""Authentication and user administration.

Login-endpoint behaviour worth spelling out, because each choice is defensive:

  • One error message for every failure. "No such user" versus "wrong password"
    tells an attacker which usernames are real; a single generic message tells
    them nothing.
  • A password check runs even when the username does not exist, against a
    dummy hash. Otherwise the response time itself answers the enumeration
    question the error message refused to.
  • Failures are counted per account (lockout) *and* per source address (rate
    limit). Account-only counting lets one attacker lock every officer out of
    their own system — a denial-of-service dressed as a security control — so
    the address limit is what actually absorbs a spray, and the lockout is
    scoped and self-clearing.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, func, select

from app.config import settings
from app.database import get_session
from app.models import User
from app.security import roles
from app.security.context import Actor
from app.security.deps import (client_ip, current_user, require_admin, utcnow)
from app.security.passwords import (PasswordPolicyError, check_policy,
                                    hash_password, needs_rehash, verify_password)
from app.security.ratelimit import limiter, parse_spec
from app.security.tokens import issue_access_token
from app.services.audit import log_action
from app.services.serializers import iso

log = logging.getLogger("sentinel.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the username is unknown, so the response takes the same
# time either way. The password is random and unknowable by construction.
_DUMMY_HASH = hash_password("no-such-user-timing-equaliser")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=1, max_length=1024)
    full_name: str = ""
    badge_number: str = ""
    unit: str = ""
    role: str = roles.ANALYST


class UserUpdate(BaseModel):
    full_name: str | None = None
    badge_number: str | None = None
    unit: str | None = None
    role: str | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=1024)


def _public(u: User) -> dict:
    """Never includes password_hash or token_version."""
    return {
        "id": u.id, "username": u.username, "full_name": u.full_name,
        "badge_number": u.badge_number, "unit": u.unit, "role": u.role,
        "active": u.active, "must_change_password": u.must_change_password,
        "last_login_at": iso(u.last_login_at) if u.last_login_at else None,
        "created_at": iso(u.created_at),
    }


def _anon_actor(request: Request) -> Actor:
    """Actor for pre-authentication events, so failed logins are still traceable."""
    return Actor(ip=client_ip(request),
                 user_agent=request.headers.get("user-agent", "")[:300])


@router.post("/login")
def login(body: LoginRequest, request: Request,
          session: Session = Depends(get_session)) -> dict:
    ip = client_ip(request)
    limit, window = parse_spec(settings.RATE_LIMIT_LOGIN)
    allowed, retry_after = limiter.check(f"login:{ip}", limit, window)
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many sign-in attempts. Please wait.",
                            headers={"Retry-After": str(retry_after)})

    username = body.username.strip().lower()
    user = session.exec(select(User).where(col(User.username) == username)).first()
    now = utcnow()

    if user is None:
        verify_password(body.password, _DUMMY_HASH)   # equalise timing
        log_action(session, "login_failed", "", {"username": username,
                                                 "reason": "unknown_user"},
                   actor=_anon_actor(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")

    if user.locked_until and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds())
        log_action(session, "login_blocked", user.id, {"username": username,
                                                       "reason": "locked"},
                   actor=_anon_actor(request))
        raise HTTPException(status.HTTP_423_LOCKED,
                            "Account temporarily locked after repeated failed "
                            "sign-ins. Try again later.",
                            headers={"Retry-After": str(max(1, remaining))})

    if not verify_password(body.password, user.password_hash) or not user.active:
        user.failed_attempts += 1
        reason = "bad_password" if user.active else "inactive_account"
        if user.failed_attempts >= settings.LOGIN_MAX_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            user.failed_attempts = 0
            reason = "locked_out"
        user.updated_at = now
        session.add(user)
        session.commit()
        log_action(session, "login_failed", user.id,
                   {"username": username, "reason": reason},
                   actor=_anon_actor(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password.")

    # Success — clear the counters and upgrade the hash if the work factor moved.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = ip
    user.updated_at = now
    session.add(user)
    session.commit()
    session.refresh(user)
    limiter.reset(f"login:{ip}")

    token, expires_in = issue_access_token(
        user_id=user.id, username=user.username, role=user.role,
        token_version=user.token_version)
    log_action(session, "login_success", user.id, {"username": user.username},
               actor=Actor(id=user.id, username=user.username, role=user.role,
                           badge=user.badge_number, ip=ip,
                           user_agent=request.headers.get("user-agent", "")[:300]))
    return {"access_token": token, "token_type": "bearer",
            "expires_in": expires_in, "user": _public(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return _public(user)


@router.post("/logout")
def logout(request: Request, user: User = Depends(current_user),
           session: Session = Depends(get_session)) -> dict:
    """Revokes every token issued to this user, not just the one presented.

    Bearer tokens are self-contained, so "log out" can only mean invalidating
    them server-side. Bumping token_version does exactly that.
    """
    user.token_version += 1
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    log_action(session, "logout", user.id, {"username": user.username})
    return {"ok": True}


@router.post("/change-password")
def change_password(body: PasswordChange, user: User = Depends(current_user),
                    session: Session = Depends(get_session)) -> dict:
    if not verify_password(body.current_password, user.password_hash):
        log_action(session, "password_change_failed", user.id,
                   {"reason": "bad_current_password"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect.")
    if body.new_password == body.current_password:
        raise HTTPException(422, "New password must differ from the current one.")
    try:
        check_policy(body.new_password, username=user.username)
    except PasswordPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc

    now = utcnow()
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = now
    user.must_change_password = False
    user.updated_at = now
    # Force every other session to re-authenticate with the new credential.
    user.token_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    log_action(session, "password_changed", user.id, {"username": user.username})

    token, expires_in = issue_access_token(
        user_id=user.id, username=user.username, role=user.role,
        token_version=user.token_version)
    return {"ok": True, "access_token": token, "token_type": "bearer",
            "expires_in": expires_in, "user": _public(user)}


# ── user administration (admin only) ────────────────────────────────────────

@router.get("/users")
def list_users(session: Session = Depends(get_session),
               _: User = Depends(require_admin)) -> list[dict]:
    rows = session.exec(select(User).order_by(col(User.created_at).desc())).all()
    return [_public(u) for u in rows]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, session: Session = Depends(get_session),
                admin: User = Depends(require_admin)) -> dict:
    username = body.username.strip().lower()
    if not username.isascii() or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise HTTPException(422, "Username may contain only letters, digits, dot, dash and underscore.")
    if not roles.is_valid(body.role):
        raise HTTPException(422, f"role must be one of {list(roles.ROLES)}")
    if session.exec(select(User).where(col(User.username) == username)).first():
        raise HTTPException(409, "That username is already taken.")
    try:
        check_policy(body.password, username=username)
    except PasswordPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc

    u = User(username=username, full_name=body.full_name.strip(),
             badge_number=body.badge_number.strip(), unit=body.unit.strip(),
             role=body.role, password_hash=hash_password(body.password),
             must_change_password=True)
    session.add(u)
    session.commit()
    session.refresh(u)
    log_action(session, "user_created", u.id,
               {"username": u.username, "role": u.role, "by": admin.username})
    return _public(u)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserUpdate,
                session: Session = Depends(get_session),
                admin: User = Depends(require_admin)) -> dict:
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(404, "No such user.")
    data = body.model_dump(exclude_none=True)
    if "role" in data and not roles.is_valid(data["role"]):
        raise HTTPException(422, f"role must be one of {list(roles.ROLES)}")

    # An admin must not be able to lock themselves out of user administration,
    # nor leave the system with no administrator at all.
    if u.id == admin.id and ("role" in data and data["role"] != roles.ADMIN
                             or data.get("active") is False):
        raise HTTPException(422, "You cannot demote or deactivate your own account.")
    if u.role == roles.ADMIN and (data.get("role", roles.ADMIN) != roles.ADMIN
                                  or data.get("active") is False):
        others = session.exec(
            select(User).where(col(User.role) == roles.ADMIN,
                               col(User.active) == True,  # noqa: E712
                               col(User.id) != u.id)).first()
        if not others:
            raise HTTPException(422, "This is the last active administrator.")

    for k, v in data.items():
        setattr(u, k, v)
    u.updated_at = utcnow()
    # Role or activation changes must take effect now, not at token expiry.
    if "role" in data or "active" in data:
        u.token_version += 1
    session.add(u)
    session.commit()
    session.refresh(u)
    log_action(session, "user_updated", u.id,
               {"username": u.username, "fields": sorted(data), "by": admin.username})
    return _public(u)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, body: PasswordReset,
                   session: Session = Depends(get_session),
                   admin: User = Depends(require_admin)) -> dict:
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(404, "No such user.")
    try:
        check_policy(body.new_password, username=u.username)
    except PasswordPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = utcnow()
    u.password_hash = hash_password(body.new_password)
    u.password_changed_at = now
    u.must_change_password = True     # the admin knows this password; the user must replace it
    u.failed_attempts = 0
    u.locked_until = None
    u.token_version += 1
    u.updated_at = now
    session.add(u)
    session.commit()
    log_action(session, "user_password_reset", u.id,
               {"username": u.username, "by": admin.username})
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204)
def deactivate_user(user_id: str, session: Session = Depends(get_session),
                    admin: User = Depends(require_admin)) -> None:
    """Deactivates rather than deletes.

    Audit rows reference the actor by id; hard-deleting the user would leave
    historical entries pointing at nothing, which is precisely the record a
    chain-of-custody log exists to preserve.
    """
    u = session.get(User, user_id)
    if not u:
        raise HTTPException(404, "No such user.")
    if u.id == admin.id:
        raise HTTPException(422, "You cannot deactivate your own account.")
    if u.role == roles.ADMIN:
        others = session.exec(
            select(User).where(col(User.role) == roles.ADMIN,
                               col(User.active) == True,  # noqa: E712
                               col(User.id) != u.id)).first()
        if not others:
            raise HTTPException(422, "This is the last active administrator.")
    u.active = False
    u.token_version += 1
    u.updated_at = utcnow()
    session.add(u)
    session.commit()
    log_action(session, "user_deactivated", u.id,
               {"username": u.username, "by": admin.username})


# ── security posture (admin only) ───────────────────────────────────────────

@router.get("/security-posture")
def security_posture(session: Session = Depends(get_session),
                     _: User = Depends(require_admin)) -> dict:
    """A checklist of the settings that decide how hard this instance is to
    break into, evaluated live rather than documented in a README nobody opens.

    Admin-only because it is a map of the weak points. `severity` is what the
    panel sorts on: "critical" means fix before this holds real case data.
    """
    from app.database import IS_SQLITE

    checks: list[dict] = []

    def add(key: str, ok: bool, severity: str, title: str, detail: str) -> None:
        checks.append({"key": key, "ok": ok, "severity": severity,
                       "title": title, "detail": detail})

    # Is anyone still signing in with the credential published in config.py?
    default_pw = settings.BOOTSTRAP_ADMIN_PASSWORD
    using_default = []
    if default_pw:
        for u in session.exec(select(User).where(col(User.active) == True)).all():  # noqa: E712
            if verify_password(default_pw, u.password_hash):
                using_default.append(u.username)
    add("default_password", not using_default, "critical",
        "Shipped default password",
        f"In use by: {', '.join(using_default)}. That value is published with "
        f"the source code. Change it here or set BOOTSTRAP_ADMIN_PASSWORD."
        if using_default else
        "No account is using the password that ships in config.py.")

    add("secret_key", bool(settings.SECRET_KEY), "critical",
        "Token signing key",
        "SECRET_KEY is set, so sessions survive a restart and multiple workers "
        "agree on who is signed in."
        if settings.SECRET_KEY else
        "SECRET_KEY is unset — a random key is generated at boot. Every restart "
        "signs everyone out, and more than one worker will reject each other's "
        "tokens outright.")

    add("transport", settings.ENABLE_HSTS, "high", "HTTPS enforcement",
        "HSTS is being sent." if settings.ENABLE_HSTS else
        "HSTS is off. Correct for local HTTP; turn ENABLE_HSTS on the moment "
        "this sits behind TLS, or credentials travel in clear text.")

    add("biometric_encryption", bool(settings.BIOMETRIC_ENCRYPTION_KEY), "high",
        "Biometrics encrypted at rest",
        "Face templates and mugshots are encrypted."
        if settings.BIOMETRIC_ENCRYPTION_KEY else
        "BIOMETRIC_ENCRYPTION_KEY is unset — face templates are stored in the "
        "clear. Allowed for a demo, refused on a live deployment.")

    add("durable_storage", not IS_SQLITE, "medium", "Durable shared database",
        "Postgres — the record is shared, backed up and survives this host."
        if not IS_SQLITE else
        "SQLite. Everything lives in one file on this machine; there is no "
        "replication and no point-in-time restore. Point DATABASE_URL at "
        "Supabase for a durable corpus.")

    add("rate_limiting", settings.RATE_LIMIT_ENABLED, "high", "Rate limiting",
        f"On — {settings.RATE_LIMIT_DEFAULT} general, "
        f"{settings.RATE_LIMIT_LOGIN} on sign-in."
        if settings.RATE_LIMIT_ENABLED else
        "Disabled. Brute-force protection is down to the account lockout alone.")

    add("cors", "*" not in settings.CORS_ORIGINS, "critical", "Browser origins",
        f"Restricted to {len(settings.CORS_ORIGINS)} origin(s).")

    add("allowed_hosts", "*" not in settings.ALLOWED_HOSTS, "medium",
        "Host header allowlist",
        f"Restricted to {len(settings.ALLOWED_HOSTS)} host(s)."
        if "*" not in settings.ALLOWED_HOSTS else
        "Any Host header is accepted. Fine for a demo, not for a deployment.")

    add("proxy_headers", not settings.TRUST_PROXY_HEADERS
        or not settings.SIMULATION_ENABLED, "medium", "Proxy header trust",
        "X-Forwarded-For is ignored, so audit-log addresses cannot be forged."
        if not settings.TRUST_PROXY_HEADERS else
        "X-Forwarded-For is trusted. Only correct when a reverse proxy you "
        "control sets it — otherwise callers choose what the audit log records.")

    add("assistant_scope", True, "info", "Voice assistant scope",
        "Sentinel is read-only and refuses accounts, credentials, the audit "
        "trail, biometrics and every write. Its budget is "
        f"{settings.RATE_LIMIT_ASSISTANT} requests." if settings.ASSISTANT_ENABLED
        else "The voice assistant is disabled on this instance.")

    # Accounts worth an admin's attention regardless of configuration.
    stale = session.exec(select(User).where(col(User.active) == True,  # noqa: E712
                                            col(User.must_change_password) == True)).all()  # noqa: E712
    locked = session.exec(select(User).where(
        col(User.locked_until) != None)).all()  # noqa: E711

    return {
        "checks": checks,
        "failing": sum(1 for c in checks if not c["ok"]),
        "accounts": {
            "total": session.exec(select(func.count()).select_from(User)).one(),
            "active": session.exec(select(func.count()).select_from(User)
                                   .where(col(User.active) == True)).one(),  # noqa: E712
            "admins": session.exec(select(func.count()).select_from(User)
                                   .where(col(User.role) == roles.ADMIN,
                                          col(User.active) == True)).one(),  # noqa: E712
            "pending_password_change": [u.username for u in stale],
            "locked_out": [u.username for u in locked
                           if u.locked_until and u.locked_until > utcnow()],
        },
    }


# ── audit trail (supervisor+) ───────────────────────────────────────────────

@router.get("/audit")
def read_audit(limit: int = 100, action: str = "", actor: str = "",
               session: Session = Depends(get_session),
               _: User = Depends(require_admin)) -> list[dict]:
    """Read the chain-of-custody log. Admin-only: it names who investigated whom."""
    from app.models import AuditLog

    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(col(AuditLog.action) == action)
    if actor:
        stmt = stmt.where(col(AuditLog.actor_username) == actor.strip().lower())
    rows = session.exec(
        stmt.order_by(col(AuditLog.created_at).desc()).limit(max(1, min(limit, 500)))
    ).all()
    return [{"id": r.id, "action": r.action, "target_id": r.target_id,
             "actor_id": r.actor_id, "actor_username": r.actor_username,
             "actor_role": r.actor_role, "actor_badge": r.actor_badge,
             "ip": r.ip, "user_agent": r.user_agent, "details": r.details,
             "created_at": iso(r.created_at)} for r in rows]
