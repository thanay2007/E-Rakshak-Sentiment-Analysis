"""Provisioned administrator.

Runs on every boot and is idempotent *by username*: the account is created if
it is absent and then never touched again. That distinction matters — the
obvious implementation ("re-apply the configured password at startup") would
silently undo a password change made in the Admin Panel, so the credential in
the config file would quietly remain the real one forever.

There is a second account path here for the same reason there are two kinds of
deployment. A configured password (BOOTSTRAP_ADMIN_PASSWORD) gives the Surat
console a working sign-in out of the box; leaving it blank generates a random
one, prints it to the server log exactly once, and forces a change at first
sign-in. The shipped default is a *known* credential — it lives in config.py,
which lives in the repository — so while it is still in force this module warns
about it at every single boot rather than once at creation. A warning you only
see on the day you install is a warning nobody reads.
"""
from __future__ import annotations

import logging
import secrets

from sqlmodel import col, func, select

from app.config import settings
from app.database import session_scope
from app.models import User
from app.security import roles
from app.security.passwords import hash_password, verify_password

log = logging.getLogger("sentinel.auth")

_BANNER = "=" * 72


def ensure_admin_exists() -> None:
    """Create the configured administrator if no account holds that username."""
    username = (settings.BOOTSTRAP_ADMIN_USERNAME or "admin").strip().lower()
    password = settings.BOOTSTRAP_ADMIN_PASSWORD
    generated = not password
    if generated:
        password = secrets.token_urlsafe(18)

    with session_scope() as s:
        existing = s.exec(select(User).where(col(User.username) == username)).first()
        if existing is not None:
            _warn_if_default_password_still_set(existing, password, generated)
            return

        # A different administrator already runs this instance: create the
        # configured one anyway (it is what the operator asked for), but do not
        # pretend this is a first boot.
        others = s.exec(select(func.count()).select_from(User)).one()

        s.add(User(
            username=username,
            full_name=settings.BOOTSTRAP_ADMIN_FULL_NAME or "Administrator",
            unit=settings.BOOTSTRAP_ADMIN_UNIT,
            role=roles.ADMIN,
            password_hash=hash_password(password),
            # A generated password is a transport credential and must be
            # replaced; a deliberately configured one is the operator's choice.
            must_change_password=generated or settings.BOOTSTRAP_ADMIN_FORCE_CHANGE,
        ))
        s.commit()

    if generated:
        log.warning(
            "\n%s\nCreated administrator '%s' with a generated password.\n"
            "    password: %s\n"
            "It is shown once and is not recoverable. Sign in and change it now;\n"
            "the account cannot be used for anything else until you do.\n%s",
            _BANNER, username, password, _BANNER)
    else:
        log.warning(
            "\n%s\nCreated administrator '%s' from BOOTSTRAP_ADMIN_PASSWORD.\n"
            "%s existing account(s) were left untouched.\n%s",
            _BANNER, username, others, _BANNER)


def _warn_if_default_password_still_set(user: User, password: str,
                                        generated: bool) -> None:
    """Nag, every boot, for as long as the credential from config.py is live.

    Checking by verifying the configured password against the stored hash is
    the only honest test: the hash is one-way, so "has this been changed?"
    cannot be answered any other way, and it stays correct if someone changes
    the password and later changes it back.
    """
    if generated or not password:
        return
    if not verify_password(password, user.password_hash):
        return          # operator has replaced it — nothing to say
    log.warning(
        "\n%s\nSECURITY: administrator '%s' is still using the password shipped\n"
        "in config.py. That value is published with the source code, so it is\n"
        "public. Set BOOTSTRAP_ADMIN_PASSWORD in backend/.env, or change the\n"
        "password from Admin Panel → Officers, before this instance holds real\n"
        "case data.\n%s", _BANNER, user.username, _BANNER)
