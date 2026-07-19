"""Ingestion pipeline: RawPost -> dedupe -> NLP enrichment -> DB -> alerts -> WS push.

Also owns first-boot seeding so a fresh clone shows a fully populated
dashboard (SEED_HISTORY_HOURS of simulated multilingual history).
"""
import hashlib
import logging

from sqlmodel import select

from app.config import settings
from app.database import session_scope
from app.data.simulator import get_simulator
from app.ml.geo import infer_city
from app.ml.pipeline import get_pipeline
from app.models import Alert, Post
from app.schemas import RawPost
from app.services.serializers import alert_to_dict, post_to_dict
from app.services.websocket_manager import manager

log = logging.getLogger("sentinel.ingest")


def content_hash(raw: RawPost) -> str:
    key = f"{raw.platform}|{raw.author_handle}|{raw.text}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _make_post(raw: RawPost, nlp: dict, chash: str) -> Post:
    if not raw.location:  # live-platform posts: geo-tag from city mentions
        hit = infer_city(raw.text)
        if hit:
            raw.location, raw.latitude, raw.longitude = hit
    elif not raw.latitude and not raw.longitude:  # seed-source :City tag → coords
        from app.data.templates import CITIES

        raw.latitude, raw.longitude = CITIES.get(raw.location, (0.0, 0.0))
    post = Post(
        content_hash=chash,
        platform=raw.platform,
        author_handle=raw.author_handle, author_name=raw.author_name,
        author_followers=raw.author_followers, author_verified=raw.author_verified,
        author_account_age_days=raw.author_account_age_days,
        text=raw.text,
        # simulated posts carry their own gloss; live non-English posts get a
        # Groq machine translation during enrichment
        translation=nlp.pop("translation", "") or raw.translation,
        hashtags=raw.hashtags, location=raw.location,
        latitude=raw.latitude, longitude=raw.longitude,
        engagement=raw.engagement, url=raw.url, media_urls=raw.media_urls,
        cluster_id=raw.cluster_id, is_amplified=raw.is_amplified,
        true_label=raw.true_label,
        created_at=raw.created_at or None,
        **nlp,
    )
    from app.ml.bot_classifier import is_likely_bot
    if is_likely_bot(post):
        # store the bot flag in the JSON column to avoid a schema migration
        post.class_probs = {**(post.class_probs or {}), "is_bot": True}
    return post


def _maybe_alert(post: Post) -> Alert | None:
    """Threat-score bands -> alert severity; critical alerts ship with an
    auto-generated escalation template (the 'automated escalation' bonus)."""
    score = post.threat_score
    signals = set(post.hate_flags or [])
    if score >= settings.CRITICAL_THRESHOLD:
        severity = "critical"
    elif score >= settings.ALERT_THRESHOLD:
        severity = "high"
    elif score >= 55 and ({"targets_official", "mobilization"} & signals):
        severity = "medium"
    else:
        return None

    escalation = {}
    if severity == "critical":
        from app.services.report_service import escalation_template
        from app.services.notifications import send_critical_alert_notification

        escalation = escalation_template(post)
        snippet = (post.translation or post.text)[:160]
        send_critical_alert_notification(
            alert_title=f"{post.threat_label} — {post.location or post.platform}",
            alert_summary=snippet,
            location=post.location
        )

    snippet = (post.translation or post.text)[:160]
    return Alert(
        post_id=post.id,
        severity=severity,
        title=f"{post.threat_label} — {post.location or post.platform}",
        summary=snippet,
        category=post.threat_label,
        location=post.location,
        platform=post.platform,
        threat_score=score,
        escalation=escalation,
    )


async def ingest(raws: list[RawPost]) -> int:
    """Process a batch of raw posts. Returns number of new posts stored."""
    if not raws:
        return 0
    hashes = {content_hash(r): r for r in raws}  # in-batch dedupe too

    new_posts: list[Post] = []
    new_alerts: list[Alert] = []
    with session_scope() as s:
        existing = set(s.exec(
            select(Post.content_hash).where(Post.content_hash.in_(list(hashes)))
        ).all())
        fresh = {h: r for h, r in hashes.items() if h not in existing}
        if not fresh:
            return 0

        fresh_raws = list(fresh.values())
        enriched = get_pipeline().enrich_batch(fresh_raws)
        # LLM second opinion on the risky subset BEFORE alerts fire (no-op
        # without GROQ_API_KEY) — see services/groq_verifier.py
        from app.services.groq_verifier import translate_enriched, verify_enriched
        await verify_enriched([r.text for r in fresh_raws], enriched)
        # English gloss for every non-English post (Groq MT)
        await translate_enriched([r.text for r in fresh_raws], enriched)
        # Cross-source corroboration of suspected fake news (Google News RSS)
        from app.services.fact_check import corroborate_enriched
        await corroborate_enriched([r.text for r in fresh_raws], enriched)
        for (chash, raw), nlp in zip(fresh.items(), enriched):
            post = _make_post(raw, nlp, chash)
            s.add(post)
            new_posts.append(post)
            alert = _maybe_alert(post)
            if alert:
                s.add(alert)
                new_alerts.append(alert)
        s.commit()
        for p in new_posts:
            s.refresh(p)
        for a in new_alerts:
            s.refresh(a)

        post_msgs = [post_to_dict(p, full=True) for p in new_posts]
        alert_msgs = [alert_to_dict(a) for a in new_alerts]

    for msg in post_msgs:
        await manager.broadcast({"type": "post", "data": msg})
    for msg in alert_msgs:
        await manager.broadcast({"type": "alert", "data": msg})
    return len(post_msgs)


def seed_if_empty() -> int:
    """First boot: backfill simulated history so the dashboard is alive immediately.
    Skipped in live mode (SIMULATION_ENABLED=false) — the portal then shows
    only real collected posts."""
    if not settings.SIMULATION_ENABLED:
        return 0
    with session_scope() as s:
        if s.exec(select(Post.id).limit(1)).first():
            return 0
        log.info("Empty database — seeding %sh of simulated history...", settings.SEED_HISTORY_HOURS)
        raws = get_simulator().history(hours=settings.SEED_HISTORY_HOURS)
        pipeline = get_pipeline()
        seen: set[str] = set()
        count = 0
        for i in range(0, len(raws), 200):
            chunk = raws[i:i + 200]
            enriched = pipeline.enrich_batch(chunk)
            for raw, nlp in zip(chunk, enriched):
                chash = content_hash(raw)
                if chash in seen:
                    continue
                seen.add(chash)
                post = _make_post(raw, nlp, chash)
                s.add(post)
                s.flush()
                alert = _maybe_alert(post)
                if alert:
                    s.add(alert)
                count += 1
        s.commit()
        log.info("Seeded %d posts", count)
        return count
