"""Request-scoped identity, carried in a ContextVar.

Why a ContextVar rather than threading an `actor` argument through every
service call: the audit log must record who acted, and the moment that
depends on a caller remembering to pass an argument, some call site will
forget and silently write an anonymous row. Attribution has to be the
default, not an opt-in.

ContextVars propagate correctly here — FastAPI resolves dependencies and runs
async endpoints in one task context, and sync endpoints go through anyio's
threadpool, which copies the context into the worker thread.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    """Who is making the current request, flattened for the audit log."""
    id: str = ""
    username: str = ""
    role: str = ""
    badge: str = ""
    ip: str = ""
    user_agent: str = ""

    @property
    def is_authenticated(self) -> bool:
        return bool(self.id)


SYSTEM = Actor(id="system", username="system", role="system")
"""Used by the scheduler and other unattended jobs, so background writes are
distinguishable from anything a human did."""

_current: ContextVar[Actor | None] = ContextVar("sentinel_actor", default=None)


def set_actor(actor: Actor):
    """Returns the token needed to restore the previous value."""
    return _current.set(actor)


def reset_actor(token) -> None:
    _current.reset(token)


def get_actor() -> Actor:
    return _current.get() or Actor()
