"""Incident/escalation report generation: structured JSON payloads + styled
PDF files (reportlab). Critical alerts get an auto-filled escalation template
at ingestion time.

Reports state what the system measured — sentiment split, concern scores, where
negative sentiment concentrated, and which posts drove it — and stop there. They
do not assert that a post is incitement or misinformation, because nothing in
the pipeline establishes that; a report an officer may attach to a case file is
the last place to blur the line between a measurement and a conclusion."""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlmodel import select

from app.config import settings
from app.database import session_scope
from app.models import Alert, Post, Report
from app.services.serializers import iso, post_to_dict

from app.ml.score import band as _band

log = logging.getLogger("sentinel.reports")

# Recommended actions are keyed by the CONCERN BAND, not by a category. The
# system reports that a post is strongly negative and spreading; what an officer
# should do about that is a function of how severe and how widely read it is,
# which the score already captures. Keying these off an asserted category would
# have meant recommending a takedown request on the strength of a model's guess
# that a post "is incitement" — a claim it can no longer make.
RECOMMENDED_ACTIONS = {
    "critical": [
        "Review the post directly and confirm the reading before acting on it",
        "Notify the police station with jurisdiction over the referenced location",
        "Preserve evidence: archive post URL, screenshots and author profile",
        "Cross-check the author against prior incident records",
    ],
    "high": [
        "Add the author and associated hashtags to the active watchlist",
        "Monitor for escalation and for coordinated re-posting",
        "Brief community-liaison officers for the affected area",
    ],
    "elevated": [
        "Keep under passive monitoring; no action indicated on this post alone",
        "Track share velocity in case the sentiment spreads",
    ],
}


def escalation_template(post: Post) -> dict:
    """Pre-filled escalation packet attached to critical alerts automatically."""
    return {
        "incident_type": f"{post.sentiment_label} sentiment, concern {round(post.concern_score)}/100",
        "priority": "P1 — IMMEDIATE",
        "generated_by": "SENTINEL automated escalation",
        "generated_at": iso(datetime.now(timezone.utc).replace(tzinfo=None)),
        "platform": post.platform,
        "source_url": post.url,
        "location": post.location,
        "language": post.language,
        "author": {
            "handle": post.author_handle, "name": post.author_name,
            "followers": post.author_followers,
            "account_age_days": post.author_account_age_days,
        },
        "evidence": {
            "original_text": post.text,
            "english_translation": post.translation,
            "concern_score": post.concern_score,
            "sentiment": f"{post.sentiment_label} ({post.sentiment_confidence:.0%} confidence)",
            "how_the_score_was_built": (post.sentiment_consensus or {}).get("score_breakdown", []),
            "evidence_sources": [e.get("source") for e
                                 in (post.sentiment_consensus or {}).get("evidence", [])],
            "flags": post.hate_flags or [],
            "matched_keywords": post.keywords or [],
        },
        "recommended_actions": RECOMMENDED_ACTIONS.get(_band(post.concern_score), [])[:3],
        "note": "Automated triage output — requires analyst verification before action.",
    }


def _build_payload(period_hours: int) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=period_hours)
    with session_scope() as s:
        posts = s.exec(select(Post).where(Post.created_at >= since)).all()
        alerts = s.exec(select(Alert).where(Alert.created_at >= since)).all()

    from app.services.network_service import get_network
    from app.services.trend_service import get_trends

    network = get_network(period_hours)
    trends = get_trends(period_hours)

    negative = [p for p in posts if p.sentiment_label == "negative"]
    top = sorted(posts, key=lambda p: -p.concern_score)[:6]
    label_counts = Counter(p.sentiment_label for p in posts)
    flagged = [p for p in posts if p.concern_score >= settings.ALERT_THRESHOLD]

    summary = (
        f"In the last {period_hours}h SENTINEL processed {len(posts)} posts across "
        f"{len({p.platform for p in posts})} platforms. Sentiment split "
        f"{label_counts.get('negative', 0)} negative / "
        f"{label_counts.get('neutral', 0)} neutral / "
        f"{label_counts.get('positive', 0)} positive; {len(flagged)} posts scored at or "
        f"above the concern threshold of {settings.ALERT_THRESHOLD}. "
        f"{sum(1 for a in alerts if a.severity == 'critical')} critical alerts were raised and "
        f"{len(network['clusters'])} coordinated amplification cluster(s) detected."
    )

    actions: list[str] = []
    for b, _ in Counter(_band(p.concern_score) for p in negative).most_common():
        actions.extend(RECOMMENDED_ACTIONS.get(b, [])[:2])

    return {
        "summary": summary,
        "period_hours": period_hours,
        "generated_at": iso(datetime.now(timezone.utc).replace(tzinfo=None)),
        "totals": {
            "posts": len(posts),
            "negative_posts": len(negative),
            "flagged_posts": len(flagged),
            "alerts": len(alerts),
            "critical_alerts": sum(1 for a in alerts if a.severity == "critical"),
            "avg_concern_score": round(mean(p.concern_score for p in posts), 1) if posts else 0,
        },
        "sentiment_distribution": dict(label_counts),
        "language_distribution": dict(Counter(p.language for p in posts)),
        "platform_distribution": dict(Counter(p.platform for p in posts)),
        "top_concern": [post_to_dict(p, full=True) for p in top],
        "coordinated_clusters": network["clusters"],
        "trending_hashtags": trends["hashtags"][:8],
        "regions": trends["regions"][:8],
        "recommended_actions": actions[:6],
    }


def _render_pdf(report: Report) -> str:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        log.warning("reportlab missing — skipping PDF render")
        return ""

    path = settings.REPORTS_DIR / f"{report.id}.pdf"
    p = report.payload
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=colors.HexColor("#0F1420"), fontSize=18)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor("#14B8C4"))
    body = styles["BodyText"]

    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    flow = [
        Paragraph("SENTINEL — Public Sentiment Report", h1),
        Paragraph(f"{report.title} • generated {p.get('generated_at', '')} • window {p.get('period_hours')}h", body),
        Spacer(1, 6 * mm),
        Paragraph("Executive Summary", h2),
        Paragraph(p.get("summary", ""), body),
        Spacer(1, 4 * mm),
        Paragraph("Sentiment Breakdown", h2),
    ]
    dist = p.get("sentiment_distribution", {})
    table = Table([["Sentiment", "Posts"]] + [[k, str(v)] for k, v in dist.items()], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F1420")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    flow.append(table)

    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph("Highest-Concern Posts", h2))
    for t in p.get("top_concern", [])[:5]:
        flow.append(Paragraph(
            f"<b>[{t['concern_score']}] {t['sentiment_label']}</b> — {t['platform']} @{t['author_handle']} "
            f"({t['language']}, {t['location'] or 'n/a'})", body))
        flow.append(Paragraph(t.get("translation") or t.get("text", ""), body))
        flow.append(Spacer(1, 2 * mm))

    clusters = p.get("coordinated_clusters", [])
    if clusters:
        flow.append(Paragraph("Coordinated Amplification", h2))
        for c in clusters[:4]:
            flow.append(Paragraph(
                f"<b>{c['id']} — {c['label']}</b> (confidence {c['confidence']:.0%}, "
                f"{len(c['accounts'])} accounts): {'; '.join(c['why'])}", body))
            flow.append(Spacer(1, 2 * mm))

    flow.append(Paragraph("Recommended Actions", h2))
    for a in p.get("recommended_actions", []):
        flow.append(Paragraph(f"• {a}", body))

    doc.build(flow)
    return str(path)


def generate_report(title: str = "", period_hours: int = 24, kind: str = "incident") -> Report:
    payload = _build_payload(period_hours)
    report = Report(
        title=title or f"Situation Report — last {period_hours}h",
        kind=kind, period_hours=period_hours, payload=payload,
    )
    with session_scope() as s:
        s.add(report)
        s.commit()
        s.refresh(report)
        report.pdf_path = _render_pdf(report)
        s.add(report)
        s.commit()
        s.refresh(report)
        # detach a plain copy
        s.expunge(report)
    return report
