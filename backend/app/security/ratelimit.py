"""In-process sliding-window rate limiter.

Scope, stated honestly: counters live in this process's memory. That is correct
for the current single-instance deployment and for slowing down brute force and
runaway clients. It is NOT a distributed limiter — run two workers and each
enforces its own budget. Moving to gunicorn/Kubernetes means moving these
counters to Redis; the `Limiter` interface below is what you would reimplement.

A sliding window (deque of timestamps) rather than a fixed window, because a
fixed window lets a caller spend the whole budget at 0:59 and again at 1:01.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from app.config import settings

_PRUNE_EVERY_SECONDS = 300


def parse_spec(spec: str) -> tuple[int, int]:
    """'20/60' → (20 requests, 60 second window)."""
    count, _, window = spec.partition("/")
    return int(count), int(window)


class Limiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()

    def check(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Records a hit. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_prune > _PRUNE_EVERY_SECONDS:
                self._prune(now)
            bucket = self._hits[key]
            cutoff = now - window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False, max(1, int(bucket[0] + window - now) + 1)
            bucket.append(now)
            return True, 0

    def reset(self, key: str) -> None:
        """Clear a key's history — used after a successful login so a legitimate
        officer who fat-fingered their password a few times isn't left throttled."""
        with self._lock:
            self._hits.pop(key, None)

    def _prune(self, now: float) -> None:
        """Drop buckets whose newest hit is older than any plausible window."""
        stale = [k for k, v in self._hits.items()
                 if not v or v[-1] < now - _PRUNE_EVERY_SECONDS]
        for k in stale:
            del self._hits[k]
        self._last_prune = now


limiter = Limiter()


def _identity(request: Request) -> str:
    """Prefer the authenticated user, fall back to source address.

    Keying on the user means one compromised account cannot exhaust the budget
    for everyone else behind the same station NAT — a real problem when an
    entire district egresses from one address.
    """
    actor = getattr(request.state, "actor", None)
    if actor is not None and getattr(actor, "id", ""):
        return f"user:{actor.id}"
    from app.security.deps import client_ip
    return f"ip:{client_ip(request)}"


def rate_limit(spec: str, *, bucket: str = "default"):
    """Dependency factory. `bucket` separates budgets so an expensive endpoint
    cannot be starved by ordinary polling traffic."""
    limit, window = parse_spec(spec)

    def _guard(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        key = f"{bucket}:{_identity(request)}"
        allowed, retry_after = limiter.check(key, limit, window)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(retry_after)})

    return _guard


def default_rate_limit(request: Request) -> None:
    """Router-wide budget, resolved from settings at call time so the value can
    be tuned in .env without touching code."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    limit, window = parse_spec(settings.RATE_LIMIT_DEFAULT)
    allowed, retry_after = limiter.check(f"default:{_identity(request)}", limit, window)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(retry_after)})


def expensive_rate_limit(request: Request) -> None:
    """For face search, outbound OSINT fetches and LLM-backed endpoints."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    limit, window = parse_spec(settings.RATE_LIMIT_EXPENSIVE)
    allowed, retry_after = limiter.check(f"expensive:{_identity(request)}", limit, window)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit reached for this tool. Please wait a moment.",
            headers={"Retry-After": str(retry_after)})


Expensive = Depends(expensive_rate_limit)
