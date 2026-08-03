"""First-boot administrator.

Runs only when the user table is empty. There is no hardcoded default
credential: if BOOTSTRAP_ADMIN_PASSWORD is unset a random one is generated and
printed to the server log exactly once, at boot, and never stored anywhere in
recoverable form. Either way the account is flagged `must_change_password`, so
the bootstrap credential cannot quietly become the permanent one.

A fixed default password ("admin/admin") would be the single worst thing this
file could do — every deployment would ship with the same known key, and the
one that never gets changed is always a real one.
"""
from __future__ import annotations

import logging
import secrets

from sqlmodel import func, select

from app.config import settings
from app.database import session_scope
from app.models import User
from app.security import roles
from app.security.passwords import hash_password

log = logging.getLogger("sentinel.auth")


def ensure_admin_exists() -> None:
    with session_scope() as s:
        if s.exec(select(func.count()).select_from(User)).one():
            return

        username = (settings.BOOTSTRAP_ADMIN_USERNAME or "admin").strip().lower()
        password = settings.BOOTSTRAP_ADMIN_PASSWORD
        generated = not password
        if generated:
            password = secrets.token_urlsafe(18)

        s.add(User(username=username, full_name="Bootstrap Administrator",
                   role=roles.ADMIN, password_hash=hash_password(password),
                   must_change_password=True))
        s.commit()

    banner = "=" * 72
    if generated:
        log.warning(
            "\n%s\nNo users existed — created the first administrator.\n"
            "    username: %s\n    password: %s\n"
            "This password is shown once and is not recoverable. Sign in and\n"
            "change it now; the account cannot be used for anything else until\n"
            "you do.\n%s", banner, username, password, banner)
    else:
        log.warning(
            "\n%s\nNo users existed — created the first administrator '%s' using\n"
            "BOOTSTRAP_ADMIN_PASSWORD from .env. Change that password on first\n"
            "sign-in and remove it from the .env file.\n%s", banner, username, banner)
