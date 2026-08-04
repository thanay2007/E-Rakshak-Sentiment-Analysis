"""Copy every record from one database into the one DATABASE_URL points at.

    python -m app.copy_db                      # from ./sentinel.db
    python -m app.copy_db --from sqlite:///other.db
    python -m app.copy_db --dry-run

Used to move an existing SQLite corpus into Supabase without losing history.
The schema is identical on both sides — both are built by the same migrations —
so this is a straight row copy, not a transformation.

Re-runnable: it reads the ids already in the destination once, then inserts
only what is missing. Interrupt it, fix the network, run it again.

Why not `session.merge()` per row, which is the obvious way to write this: it
issues a SELECT and then an INSERT for every single row. Against a Supabase
project in another region that is two round trips times however many posts you
have — a 3,400-row corpus took over twenty minutes and had not finished. One
id query plus batched inserts turns the same job into seconds, because the cost
here is network latency, not the database.

The audit tables are handled the same way for a second, harder reason: after
migration 0002 they refuse UPDATE outright, and `merge` on an existing row *is*
an UPDATE. Insert-only is not an optimisation there, it is the only thing that
works — which is the chain-of-custody guarantee doing its job.
"""
from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, create_engine, func, select

from app.config import BASE_DIR
from app.models import (Alert, AuditLog, FaceSearchLog, Post, Report, Suspect,
                        User, WatchlistItem)

# Append-only tables last: everything else is safely repeatable, so if the run
# dies partway the tables that cannot be retried have not been touched yet.
TABLES = [Post, Alert, WatchlistItem, Report, Suspect, User,
          AuditLog, FaceSearchLog]

BATCH = 500


def _copy(model, src: Session, dst: Session) -> tuple[int, int]:
    """Insert the rows the destination does not already have. Returns
    (written, skipped)."""
    rows = src.exec(select(model)).all()
    if not rows:
        return 0, 0

    # One round trip to learn what is already there, instead of one per row.
    existing = set(dst.exec(select(model.id)).all())

    written = skipped = 0
    pending = []
    for row in rows:
        if row.id in existing:
            skipped += 1
            continue
        pending.append(model(**row.model_dump()))
        if len(pending) >= BATCH:
            dst.add_all(pending)
            dst.commit()
            written += len(pending)
            pending.clear()
            print(f"      {written:,}/{len(rows) - skipped:,}", flush=True)
    if pending:
        dst.add_all(pending)
        dst.commit()
        written += len(pending)
    return written, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="source",
                    default=f"sqlite:///{(BASE_DIR / 'sentinel.db').as_posix()}",
                    help="source database URL (default: ./sentinel.db)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied, write nothing")
    args = ap.parse_args()

    from app.database import engine as target
    from app.config import settings

    if args.source == settings.DATABASE_URL:
        print("Source and destination are the same database. Nothing to do.")
        return 1

    print(f"\n  from  {args.source}")
    print(f"  to    {settings.DATABASE_URL.split('@')[-1] or settings.DATABASE_URL}\n")

    source = create_engine(args.source)

    with Session(source) as src, Session(target) as dst:
        if args.dry_run:
            for model in TABLES:
                s = src.exec(select(func.count()).select_from(model)).one()
                d = dst.exec(select(func.count()).select_from(model)).one()
                print(f"    {model.__name__:<15} source {s:>8,}   target {d:>8,}")
            print("\n  dry run — nothing written\n")
            return 0

        for model in TABLES:
            written, skipped = _copy(model, src, dst)
            note = f"  ({skipped:,} already there)" if skipped else ""
            print(f"    {model.__name__:<15} {written:>8,} copied{note}", flush=True)

    print("\n  done — verify with: python -m app.check_db\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
