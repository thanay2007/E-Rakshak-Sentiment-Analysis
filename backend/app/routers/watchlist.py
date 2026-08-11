"""Watchlist — keywords/hashtags/accounts/locations that steer the crawlers.

Beyond CRUD, this gives analysts the tooling a real monitoring desk expects:
per-term hit statistics (how often each term actually fired in the last 7
days, when, and the worst threat score it touched), curated preset packs
(one-click themed term sets), bulk paste-import, and CSV export for records.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.database import get_session
from app.security.deps import require_supervisor
from app.models import Post, WatchlistItem, User
from app.schemas import WatchlistCreate, WatchlistUpdate
from app.services.scheduler import invalidate_watch_terms
from app.services.serializers import iso

router = APIRouter()

VALID_KINDS = {"keyword", "hashtag", "account", "location"}
VALID_PRIORITIES = {"low", "medium", "high", "critical"}


def _to_dict(w: WatchlistItem) -> dict:
    return {"id": w.id, "kind": w.kind, "value": w.value, "note": w.note,
            "priority": w.priority or "medium", "category": w.category or "",
            "active": w.active, "created_at": iso(w.created_at)}


def _match(w: WatchlistItem):
    """The SQL condition for "this post fired this term"."""
    if w.kind == "account":
        handle = w.value.rstrip("*").lstrip("@").lower()
        return func.lower(Post.author_handle).like(f"{handle}%")
    if w.kind == "location":
        return (func.lower(Post.location) == w.value.lower()) | \
               func.lower(Post.text).like(f"%{w.value.lower()}%")
    # keyword | hashtag — hashtags always appear inline in the text
    needle = f"%{w.value.lower()}%"
    return func.lower(Post.text).like(needle) | \
           func.lower(Post.translation).like(needle)


def _hit_stats_bulk(session: Session, items: list[WatchlistItem],
                    since: datetime) -> dict[int, dict]:
    """How often each term actually fired, for every term at once.

    One query with a conditional aggregate per term, rather than one query per
    term. The per-term version was a textbook N+1, and an unusually expensive
    one: each of those queries is an unindexable `LIKE '%…%'` over the post
    text, so a desk with thirty watch terms scanned the table thirty times and
    paid thirty round trips to a database on another continent. Here the scan
    happens once and every term's counters come back with it.
    """
    if not items:
        return {}
    columns = []
    for w in items:
        cond = _match(w)
        columns += [func.count().filter(cond),
                    func.max(Post.created_at).filter(cond),
                    func.max(Post.concern_score).filter(cond)]

    row = session.exec(select(*columns).where(Post.created_at >= since)).one()
    # A SQLAlchemy `Row` is tuple-*like* but is not a tuple subclass, so it has
    # to be converted rather than type-checked. There are always at least three
    # columns here (one term, three aggregates), so this is never a bare scalar.
    values = list(row)

    stats: dict[int, dict] = {}
    for i, w in enumerate(items):
        n, last, top = values[i * 3:i * 3 + 3]
        stats[w.id] = {"hits_7d": int(n or 0),
                       "last_hit": iso(last) if last else None,
                       "top_threat": round(float(top), 1) if top else 0.0}
    return stats


@router.get("/watchlist")
def list_items(session: Session = Depends(get_session)) -> list[dict]:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    items = session.exec(
        select(WatchlistItem).order_by(col(WatchlistItem.created_at).desc())
    ).all()
    stats = _hit_stats_bulk(session, list(items), since)
    return [{**_to_dict(w), **stats.get(w.id, {})} for w in items]


@router.post("/watchlist", status_code=201)
def create_item(item: WatchlistCreate, session: Session = Depends(get_session)) -> dict:
    if item.kind not in VALID_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(VALID_KINDS)}")
    if item.priority not in VALID_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {sorted(VALID_PRIORITIES)}")
    w = WatchlistItem(**item.model_dump())
    session.add(w)
    session.commit()
    invalidate_watch_terms()
    session.refresh(w)
    return _to_dict(w)


class BulkItems(BaseModel):
    items: list[WatchlistCreate]


@router.post("/watchlist/bulk", status_code=201)
def bulk_create(body: BulkItems, session: Session = Depends(get_session)) -> dict:
    """Paste-import: adds every valid item, silently skipping duplicates
    (same kind + value, case-insensitive)."""
    existing = {(w.kind, w.value.lower()) for w in session.exec(select(WatchlistItem)).all()}
    added, skipped = 0, 0
    for item in body.items:
        if item.kind not in VALID_KINDS or not item.value.strip():
            skipped += 1
            continue
        key = (item.kind, item.value.strip().lower())
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        data = item.model_dump()
        data["value"] = item.value.strip()
        if data.get("priority") not in VALID_PRIORITIES:
            data["priority"] = "medium"
        session.add(WatchlistItem(**data))
        added += 1
    session.commit()
    invalidate_watch_terms()
    return {"added": added, "skipped": skipped}


@router.get("/watchlist/presets")
def list_presets() -> list[dict]:
    from app.data.watchlist_packs import pack_summaries

    return pack_summaries()


@router.post("/watchlist/presets/{slug}", status_code=201)
def apply_preset(slug: str, session: Session = Depends(get_session)) -> dict:
    """Apply a curated pack; already-present terms are skipped (idempotent)."""
    from app.data.watchlist_packs import PACKS

    pack = PACKS.get(slug)
    if not pack:
        raise HTTPException(404, f"No preset pack '{slug}'")
    existing = {(w.kind, w.value.lower()) for w in session.exec(select(WatchlistItem)).all()}
    added = 0
    for kind, value, note, priority in pack["items"]:
        if (kind, value.lower()) in existing:
            continue
        session.add(WatchlistItem(kind=kind, value=value, note=note,
                                  priority=priority, category=pack["title"]))
        added += 1
    session.commit()
    invalidate_watch_terms()
    return {"pack": pack["title"], "added": added,
            "skipped": len(pack["items"]) - added}


@router.get("/watchlist/export")
def export_csv(session: Session = Depends(get_session)) -> StreamingResponse:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["kind", "value", "priority", "category", "note", "active", "created_at"])
    for w in session.exec(select(WatchlistItem).order_by(col(WatchlistItem.kind))).all():
        wr.writerow([w.kind, w.value, w.priority, w.category, w.note,
                     "yes" if w.active else "no", iso(w.created_at)])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={
        "Content-Disposition": "attachment; filename=watchlist.csv"})


@router.patch("/watchlist/{item_id}")
def update_item(item_id: str, patch: WatchlistUpdate, session: Session = Depends(get_session)) -> dict:
    w = session.get(WatchlistItem, item_id)
    if not w:
        raise HTTPException(404, "Watchlist item not found")
    data = patch.model_dump(exclude_none=True)
    if "priority" in data and data["priority"] not in VALID_PRIORITIES:
        raise HTTPException(422, f"priority must be one of {sorted(VALID_PRIORITIES)}")
    for k, v in data.items():
        setattr(w, k, v)
    session.add(w)
    session.commit()
    invalidate_watch_terms()
    session.refresh(w)
    return _to_dict(w)


@router.delete("/watchlist/{item_id}", status_code=204)
def delete_item(item_id: str, session: Session = Depends(get_session),
                _: User = Depends(require_supervisor)) -> None:
    """Supervisor+. Removing a watchlist term silently stops detection for it,
    so the deletion is restricted and recorded."""
    from app.services.audit import log_action

    w = session.get(WatchlistItem, item_id)
    if not w:
        raise HTTPException(404, "Watchlist item not found")
    log_action(session, "watchlist_delete", w.id, {"kind": w.kind, "value": w.value})
    session.delete(w)
    session.commit()
    invalidate_watch_terms()
