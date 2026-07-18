"""Watchlist CRUD — keywords/hashtags/accounts/locations that steer the crawlers."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from app.database import get_session
from app.models import WatchlistItem
from app.schemas import WatchlistCreate, WatchlistUpdate
from app.services.serializers import iso

router = APIRouter()

VALID_KINDS = {"keyword", "hashtag", "account", "location"}


def _to_dict(w: WatchlistItem) -> dict:
    return {"id": w.id, "kind": w.kind, "value": w.value, "note": w.note,
            "active": w.active, "created_at": iso(w.created_at)}


@router.get("/watchlist")
def list_items(session: Session = Depends(get_session)) -> list[dict]:
    return [_to_dict(w) for w in session.exec(
        select(WatchlistItem).order_by(col(WatchlistItem.created_at).desc())
    ).all()]


@router.post("/watchlist", status_code=201)
def create_item(item: WatchlistCreate, session: Session = Depends(get_session)) -> dict:
    if item.kind not in VALID_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(VALID_KINDS)}")
    w = WatchlistItem(**item.model_dump())
    session.add(w)
    session.commit()
    session.refresh(w)
    return _to_dict(w)


@router.patch("/watchlist/{item_id}")
def update_item(item_id: str, patch: WatchlistUpdate, session: Session = Depends(get_session)) -> dict:
    w = session.get(WatchlistItem, item_id)
    if not w:
        raise HTTPException(404, "Watchlist item not found")
    for k, v in patch.model_dump(exclude_none=True).items():
        setattr(w, k, v)
    session.add(w)
    session.commit()
    session.refresh(w)
    return _to_dict(w)


@router.delete("/watchlist/{item_id}", status_code=204)
def delete_item(item_id: str, session: Session = Depends(get_session)) -> None:
    w = session.get(WatchlistItem, item_id)
    if not w:
        raise HTTPException(404, "Watchlist item not found")
    session.delete(w)
    session.commit()

