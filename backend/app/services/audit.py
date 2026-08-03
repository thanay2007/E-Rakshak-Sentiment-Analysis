"""Chain-of-custody logging.

Call sites keep the signature they always had — `log_action(session, action,
target_id, details)` — and the actor is filled in automatically from the
request context (security/context.py). Attribution is therefore not something
a caller can forget to do.

Writes are best-effort with respect to the caller: an audit failure is logged
loudly but never turns a successful police action into a 500. That trade-off is
deliberate and worth naming — it favours availability of the tool over
guaranteed completeness of the log. Where the log matters more than the action
(biometric search, registry deletion) use `log_action_strict`, which propagates
the failure instead.
"""
from __future__ import annotations

import logging

from sqlmodel import Session

from app.models import AuditLog
from app.security.context import Actor, get_actor

log = logging.getLogger("sentinel.audit")


def _build(action: str, target_id: str, details: dict | None,
           actor: Actor | None) -> AuditLog:
    a = actor or get_actor()
    return AuditLog(
        action=action,
        target_id=target_id or "",
        actor_id=a.id,
        actor_username=a.username,
        actor_role=a.role,
        actor_badge=a.badge,
        ip=a.ip,
        user_agent=a.user_agent,
        details=details or {},
    )


def log_action(session: Session, action: str, target_id: str = "",
               details: dict | None = None, *, actor: Actor | None = None) -> None:
    """Record an action. Never raises."""
    try:
        session.add(_build(action, target_id, details, actor))
        session.commit()
    except Exception:
        # Roll back so a failed audit insert doesn't poison the caller's session
        # and take the actual operation down with it.
        try:
            session.rollback()
        except Exception:
            pass
        log.exception("AUDIT WRITE FAILED action=%s target=%s", action, target_id)


def log_action_strict(session: Session, action: str, target_id: str = "",
                      details: dict | None = None, *,
                      actor: Actor | None = None) -> None:
    """Record an action, propagating any failure to the caller.

    For operations where an unlogged action is worse than a failed one.
    """
    session.add(_build(action, target_id, details, actor))
    session.commit()
