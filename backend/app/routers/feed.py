"""GET /api/feed — server-side filtered/paginated/sorted feed.
GET /api/feed/{id} — full NLP breakdown for the detail drawer."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_
from sqlmodel import Session, col, select

from app.database import get_session, session_scope
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
    sentiment: Optional[str] = Query(None, description="comma-separated: negative,neutral,positive"),
    location: Optional[str] = None,
    q: Optional[str] = Query(None, description="keyword / hashtag / handle"),
    min_score: float = 0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort: str = Query("recent", pattern="^(recent|score|engagement)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    session: Session = Depends(get_session)
):
    stmt = select(Post)
    if platform:
        stmt = stmt.where(col(Post.platform).in_(platform.split(",")))
    if language:
        stmt = stmt.where(col(Post.language).in_(language.split(",")))
    if sentiment:
        stmt = stmt.where(col(Post.sentiment_label).in_(sentiment.split(",")))
    if location:
        stmt = stmt.where(Post.location == location)
    if min_score > 0:
        stmt = stmt.where(Post.concern_score >= min_score)
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

    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    if sort == "score":
        stmt = stmt.order_by(col(Post.concern_score).desc(), col(Post.created_at).desc())
    elif sort == "engagement":
        stmt = stmt.order_by(func.json_extract(Post.engagement, "$.shares").desc())
    else:
        stmt = stmt.order_by(col(Post.created_at).desc())
    rows = session.exec(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = [post_to_dict(p, full=True) for p in rows]

    return FeedPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/feed/{post_id}")
def get_post(post_id: str, session: Session = Depends(get_session)) -> dict:
    post = session.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    return post_to_dict(post, full=True)


@router.post("/feed/{post_id}/translate")
async def translate_post(post_id: str) -> dict:
    """Translate one post to English on demand, from the detail drawer.

    The ingest pipeline translates what it detects, and detection is a
    heuristic: a post carrying one Gujarati word inside English prose, or a
    transliteration the marker list has never seen, can still reach an analyst
    with no gloss. This is the manual override for exactly that — the analyst
    can always ask, whatever the detector concluded, and the answer is stored
    on the post so nobody pays for it twice.
    """
    from app.services.groq_verifier import enabled, translate_enriched

    with session_scope() as s:
        post = s.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        if post.translation:
            return {"translation": post.translation, "cached": True}
        text, language = post.text, post.language
    if not text.strip():
        raise HTTPException(422, "Post has no text to translate")
    if not enabled():
        raise HTTPException(503, "Translation is unavailable — no LLM key is "
                                 "configured on this deployment")
    # Forced: the batch helper skips anything it considers already-English, and
    # an analyst asking for a translation has overruled that judgement.
    enriched = [{"language": language, "translation": ""}]
    await translate_enriched([text], enriched, force=True)
    translation = enriched[0].get("translation", "")
    if not translation:
        raise HTTPException(502, "The translator did not answer — try again")
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post:
            post.translation = translation
            s.add(post)
            s.commit()
    return {"translation": translation, "cached": False}


@router.post("/feed/{post_id}/fact-check")
async def fact_check_post(post_id: str) -> dict:
    """Analyst-triggered cross-source corroboration from the detail drawer:
    checks the post's claim against Google News India and stores the verdict
    (with the matching headlines as proof links) on the post."""
    import httpx

    from app.services.fact_check import _query_for, check_claim

    with session_scope() as s:
        post = s.get(Post, post_id)
        if not post:
            raise HTTPException(404, "Post not found")
        query = _query_for({"keywords": post.keywords or []},
                           post.translation or post.text)
    if not query:
        raise HTTPException(422, "Post has no usable terms to check")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            record = await check_claim(client, query, deep=True)
    except Exception:
        raise HTTPException(502, "News corroboration lookup failed — try again")
    with session_scope() as s:
        post = s.get(Post, post_id)
        if post:
            post.fact_check = record
            s.add(post)
            s.commit()
    return record


@router.post("/feed/{post_id}/evidence-report")
async def evidence_report(post_id: str) -> dict:
    """Analyst-triggered detailed dossier: claims assessed one by one, verbatim
    evidence quotes, cited news sources, account/risk assessment and a
    recommended action. Stored on the post."""
    from app.services.evidence import generate_report

    result = await generate_report(post_id)
    if not result.get("ok"):
        raise HTTPException(502 if "not found" not in result.get("error", "").lower() else 404,
                            result.get("error", "Dossier generation failed"))
    return result


@router.post("/feed/{post_id}/escalate")
def escalate_post(post_id: str, session: Session = Depends(get_session)) -> dict:
    """Analyst-triggered escalation from the detail drawer: files an
    escalation report pre-filled from the post's NLP evidence."""
    from app.models import Report
    from app.services.report_service import escalation_template
    from app.services.serializers import iso

    post = session.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Post not found")
    report = Report(
        title=(f"Escalation — {post.sentiment_label} sentiment "
               f"({round(post.concern_score)}/100) by @{post.author_handle}"),
        kind="escalation", period_hours=0,
        payload={"escalation": escalation_template(post)},
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return {"id": report.id, "title": report.title, "kind": report.kind,
            "created_at": iso(report.created_at), "has_pdf": False,
            "payload": report.payload}
