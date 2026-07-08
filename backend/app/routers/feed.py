"""GET /api/feed — server-side filtered/paginated/sorted feed.
GET /api/feed/{id} — full NLP breakdown for the detail drawer."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import String, cast, func, or_
from sqlmodel import col, select

from app.database import session_scope
from app.models import Post
from app.schemas import FeedPage
from app.services.serializers import post_to_dict

router = APIRouter()


def _parse_dt(v: Optional[str]) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", ""))
    except ValueError:
        raise HTTPException(422, f"Bad datetime: {v}")


@router.get("/feed", response_model=FeedPage)
def get_feed(
    platform: Optional[str] = Query(None, description="comma-separated"),
    language: Optional[str] = Query(None, description="comma-separated"),
    threat_level: Optional[str] = Query(None, description="comma-separated labels"),
    location: Optional[str] = None,
    q: Optional[str] = Query(None, description="keyword / hashtag / handle"),
    min_score: float = 0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: str = Query("recent", pattern="^(recent|score|engagement)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    stmt = select(Post)
    if platform:
        stmt = stmt.where(col(Post.platform).in_(platform.split(",")))
    if language:
        stmt = stmt.where(col(Post.language).in_(language.split(",")))
    if threat_level:
        stmt = stmt.where(col(Post.threat_label).in_(threat_level.split(",")))
    if location:
        stmt = stmt.where(Post.location == location)
    if min_score > 0:
        stmt = stmt.where(Post.threat_score >= min_score)
    if q:
        needle = f"%{q.lstrip('#').lower()}%"
        stmt = stmt.where(or_(
            func.lower(Post.text).like(needle),
            func.lower(Post.translation).like(needle),
            func.lower(Post.author_handle).like(needle),
            func.lower(cast(Post.hashtags, String)).like(needle),
        ))
    df, dt_ = _parse_dt(date_from), _parse_dt(date_to)
    if df:
        stmt = stmt.where(Post.created_at >= df)
    if dt_:
        stmt = stmt.where(Post.created_at <= dt_)

    with session_scope() as s:
        total = s.exec(select(func.count()).select_from(stmt.subquery())).one()
        if sort == "score":
            stmt = stmt.order_by(col(Post.threat_score).desc(), col(Post.created_at).desc())
        elif sort == "engagement":
            stmt = stmt.order_by(func.json_extract(Post.engagement, "$.shares").desc())
        else:
            stmt = stmt.order_by(col(Post.created_at).desc())
        rows = s.exec(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        items = [post_to_dict(p, full=True) for p in rows]

    return FeedPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/feed/{post_id}")
def get_post(post_id: str) -> dict:
    with session_scope() as s:
        post = s.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        return post_to_dict(post, full=True)


@router.post("/feed/{post_id}/escalate")
def escalate_post(post_id: str) -> dict:
    """Analyst-triggered escalation from the detail drawer: files an
    escalation report pre-filled from the post's NLP evidence."""
    from app.models import Report
    from app.services.report_service import escalation_template
    from app.services.serializers import iso

    with session_scope() as s:
        post = s.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        report = Report(
            title=f"Escalation — {post.threat_label} by @{post.author_handle}",
            kind="escalation", period_hours=0,
            payload={"escalation": escalation_template(post)},
        )
        s.add(report)
        s.commit()
        s.refresh(report)
        return {"id": report.id, "title": report.title, "kind": report.kind,
                "created_at": iso(report.created_at), "has_pdf": False,
                "payload": report.payload}
