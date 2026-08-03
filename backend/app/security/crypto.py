"""Encryption at rest for biometric data.

Face templates are irrevocable. A leaked password is rotated in a minute; a
leaked face vector identifies that person for the rest of their life, and the
registry it sits in marks them as a criminal suspect. That asymmetry is why the
templates and mugshots get their own encryption layer instead of relying solely
on filesystem permissions around sentinel.db.

Fernet (AES-128-CBC + HMAC-SHA256) — authenticated, so a tampered ciphertext
fails loudly rather than decrypting to a subtly wrong vector that would quietly
change who a search matches.

Scope, stated plainly: this protects the database file at rest — a stolen
laptop, a copied backup, a misconfigured file share. It does NOT protect
against an attacker who already has code execution on the running server, since
the process must hold the key to do its job. Defence against that is
authentication and the audit log, not this module.
"""
from __future__ import annotations

import json
import logging

from app.config import settings

log = logging.getLogger("sentinel.crypto")

_PREFIX = "enc:v1:"     # marks a sealed value, so plaintext rows stay readable
_fernet = None
_checked = False


def _cipher():
    """Lazily build the Fernet instance; None when no key is configured."""
    global _fernet, _checked
    if _checked:
        return _fernet
    _checked = True

    key = (settings.BIOMETRIC_ENCRYPTION_KEY or "").strip()
    if not key:
        if not settings.SIMULATION_ENABLED:
            raise RuntimeError(
                "BIOMETRIC_ENCRYPTION_KEY is not set and SIMULATION_ENABLED is "
                "false. A live deployment must not store face templates in "
                "clear text. Generate a key with:\n"
                "  python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"")
        log.warning(
            "BIOMETRIC_ENCRYPTION_KEY is not set — face templates and mugshots "
            "are being stored UNENCRYPTED. Acceptable for a local demo only.")
        return None

    from cryptography.fernet import Fernet
    try:
        _fernet = Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(
            "BIOMETRIC_ENCRYPTION_KEY is not a valid Fernet key (expected 32 "
            "url-safe base64-encoded bytes)."
        ) from exc
    return _fernet


def enabled() -> bool:
    return _cipher() is not None


def seal(value: str) -> str:
    """Encrypt a string. Returns it unchanged when no key is configured."""
    if not value or value.startswith(_PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        return value
    return _PREFIX + cipher.encrypt(value.encode("utf-8")).decode("ascii")


def open_(value: str) -> str:
    """Decrypt a string.

    Values without the marker are returned as-is: rows written before
    encryption was switched on stay readable, and enabling the key on an
    existing database does not require a migration window.
    """
    if not value or not value.startswith(_PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        # Sealed data with no key available — refuse rather than return
        # ciphertext that a caller would treat as a real value.
        raise RuntimeError(
            "Encrypted biometric data found but BIOMETRIC_ENCRYPTION_KEY is not "
            "set. Restore the key that was used to write this database.")
    from cryptography.fernet import InvalidToken
    try:
        return cipher.decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Biometric record failed its integrity check — it was encrypted "
            "with a different key, or the stored value has been tampered with."
        ) from exc


def seal_vector(vector: list[float]) -> str:
    return seal(json.dumps([float(x) for x in vector]))


def open_vector(sealed: str | list) -> list[float]:
    """Accepts a sealed string or a legacy plaintext list."""
    if isinstance(sealed, list):
        return [float(x) for x in sealed]
    if not sealed:
        return []
    return [float(x) for x in json.loads(open_(sealed))]
