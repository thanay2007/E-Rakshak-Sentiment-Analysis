"""Role hierarchy.

Three ranks, strictly ordered — a check is "at least this rank", never an
exact-match list, so adding a rank above `admin` later cannot silently strip
permissions from the ranks below it.

  analyst     the day-to-day seat: read the feed, run investigations, search
              faces, create and enrol registry records, generate reports.
  supervisor  everything an analyst can do, plus the irreversible calls —
              deleting registry records, escalating alerts, exporting bulk
              data, triggering crawls.
  admin       everything, plus user management, retention purges and the
              operations toolkit.
"""
from __future__ import annotations

ANALYST = "analyst"
SUPERVISOR = "supervisor"
ADMIN = "admin"

ROLES: tuple[str, ...] = (ANALYST, SUPERVISOR, ADMIN)

_RANK = {role: i for i, role in enumerate(ROLES)}


def rank(role: str) -> int:
    """Numeric rank; an unknown role ranks below everything (fail closed)."""
    return _RANK.get(role, -1)


def at_least(role: str, minimum: str) -> bool:
    return rank(role) >= rank(minimum)


def is_valid(role: str) -> bool:
    return role in _RANK
