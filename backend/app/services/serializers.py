"""DB row -> JSON dict helpers shared by REST responses and WebSocket pushes."""
from datetime import datetime

from app.models import Alert, Post


def iso(dt: datetime | None) -> str:
    return (dt.isoformat() + "Z") if dt else ""


def post_to_dict(p: Post, full: bool = False) -> dict:
    d = {
        "id": p.id,
        "platform": p.platform,
        "author_handle": p.author_handle,
        "author_name": p.author_name,
        "author_followers": p.author_followers,
        "author_verified": p.author_verified,
        "text": p.text,
        "translation": p.translation,
        "language": p.language,
        "code_mixed": p.code_mixed,
        "sentiment_label": p.sentiment_label,
        "sentiment_score": p.sentiment_score,
        "sentiment_confidence": p.sentiment_confidence,
        "sentiment_consensus": p.sentiment_consensus or {},
        "concern_score": p.concern_score,
        "hashtags": p.hashtags or [],
        "location": p.location,
        "engagement": p.engagement or {},
        "is_amplified": p.is_amplified,
        "cluster_id": p.cluster_id,
        "llm_verification": p.llm_verification or {},
        "fact_check": p.fact_check or {},
        "evidence_report": p.evidence_report or {},
        "media_urls": p.media_urls or [],
        "url": p.url,
        "created_at": iso(p.created_at),
    }
    if full:
        d.update({
            "author_account_age_days": p.author_account_age_days,
            "intent": p.intent,
            "class_probs": p.class_probs or {},
            "hate_flags": p.hate_flags or [],
            "toxicity_score": p.toxicity_score,
            "keywords": p.keywords or [],
            "latitude": p.latitude,
            "longitude": p.longitude,
            "true_label": p.true_label,
            "ingested_at": iso(p.ingested_at),
        })
    return d


def alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "post_id": a.post_id,
        "severity": a.severity,
        "status": a.status,
        "title": a.title,
        "summary": a.summary,
        "category": a.category,
        "location": a.location,
        "platform": a.platform,
        "concern_score": a.concern_score,
        "escalation": a.escalation or {},
        "created_at": iso(a.created_at),
        "updated_at": iso(a.updated_at),
    }
