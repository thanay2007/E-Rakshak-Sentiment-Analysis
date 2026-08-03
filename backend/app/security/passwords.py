"""Password hashing — scrypt from the standard library.

scrypt is memory-hard, so a stolen hash costs an attacker RAM per guess, not
just CPU. Using hashlib keeps this dependency-free: no passlib/bcrypt wheel to
audit, patch, or find broken after a Python upgrade.

Hashes are self-describing (`scrypt$N$r$p$salt$hash`). The work factor can be
raised later and old hashes still verify against the parameters they were
created with — `needs_rehash` reports which ones should be upgraded on the
user's next successful login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# 128 * N * r bytes of RAM per hash → 32 MB at these settings.
_N = 2 ** 15
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
# OpenSSL refuses scrypt above its own default cap unless maxmem is raised.
_MAXMEM = 128 * _N * _R * 2

_MIN_LENGTH = 12


class PasswordPolicyError(ValueError):
    """Raised when a proposed password fails the complexity policy."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          dklen=_DKLEN, maxmem=128 * n * r * 2)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = _derive(password, salt, _N, _R, _P)
    return f"scrypt${_N}${_R}${_P}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. Any malformed/empty hash verifies as False."""
    if not stored or not password:
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = _derive(password, _b64d(salt_b64), int(n), int(r), int(p))
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(dk, _b64d(hash_b64))


def needs_rehash(stored: str) -> bool:
    """True when a stored hash uses weaker parameters than the current policy."""
    try:
        scheme, n, r, p, _, _ = stored.split("$")
    except ValueError:
        return True
    return scheme != "scrypt" or (int(n), int(r), int(p)) != (_N, _R, _P)


def check_policy(password: str, *, username: str = "") -> None:
    """Enforce the minimum policy. Raises PasswordPolicyError with a message
    that is safe to show the user.

    Length is weighted over character-class gymnastics deliberately: a 12+
    character passphrase beats `P@ssw0rd!` on every measure that matters.
    """
    if len(password) < _MIN_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {_MIN_LENGTH} characters.")
    if username and username.lower() in password.lower():
        raise PasswordPolicyError("Password must not contain the username.")
    classes = sum([
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ])
    if classes < 3:
        raise PasswordPolicyError(
            "Password must combine at least three of: lowercase, uppercase, "
            "digits, symbols.")
    if password.lower() in _COMMON:
        raise PasswordPolicyError("That password is too common.")


# Deliberately short: a blocklist is a backstop, not the control. Length policy
# plus lockout plus rate limiting is what actually stops guessing.
_COMMON = {
    "password", "password123", "passw0rd123", "123456789012", "qwertyuiop12",
    "administrator", "police12345", "welcome12345", "changeme1234",
    "letmein12345", "sentinel1234", "erakshak1234",
}
