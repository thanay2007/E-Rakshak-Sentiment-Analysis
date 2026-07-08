"""Incident/escalation report generation: structured JSON payloads + styled
PDF files (reportlab). Critical alerts get an auto-filled escalation template
at ingestion time (the automated-escalation bonus feature)."""
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean

from sqlmodel import select

from app.config import settings
from app.database import session_scope
from app.models import Alert, Post, Report
from app.services.serializers import iso, post_to_dict

log = logging.getLogger("sentinel.reports")

RECOMMENDED_ACTIONS = {
    "Incitement to Violence": [
        "Notify local police station with jurisdiction over the referenced location",
        "Request platform takedown under IT Act Sec. 69A / platform ToS (violent threats)",
        "Preserve evidence: archive post URL, screenshots and author profile",
        "Cross-check author against prior incident database",
    ],
    "Inflammatory": [
        "Add author and associated hashtags to the active watchlist",
        "Monitor for escalation to direct calls for violence",
        "Brief community-liaison officers for the affected area",
    ],
    "Fake News": [
        "Coordinate with fact-check unit to publish a rebuttal",
        "Request platform labeling/de-amplification of the claim",
        "Track forward/share velocity for panic-risk assessment",
    ],
}


def escalation_template(post: Post) -> dict:
    """Pre-filled escalation packet attached to critical alerts automatically."""
    return {
        "incident_type": post.threat_label,
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
            "threat_score": post.threat_score,
            "classification": f"{post.threat_label} ({post.threat_confidence:.0%} confidence)",
            "flags": post.hate_flags or [],
            "matched_keywords": post.keywords or [],
        },
        "recommended_actions": RECOMMENDED_ACTIONS.get(post.threat_label, [])[:3],
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

    threats = [p for p in posts if p.threat_label != "Neutral"]
    top = sorted(posts, key=lambda p: -p.threat_score)[:6]
    label_counts = Counter(p.threat_label for p in posts)

    summary = (
        f"In the last {period_hours}h SENTINEL processed {len(posts)} posts across "
        f"{len({p.platform for p in posts})} platforms; {len(threats)} were classified as threats "
        f"({label_counts.get('Incitement to Violence', 0)} incitement, "
        f"{label_counts.get('Inflammatory', 0)} inflammatory, "
        f"{label_counts.get('Fake News', 0)} fake news). "
        f"{sum(1 for a in alerts if a.severity == 'critical')} critical alerts were raised and "
        f"{len(network['clusters'])} coordinated amplification cluster(s) detected."
    )

    actions: list[str] = []
    for label, _ in label_counts.most_common():
        if label != "Neutral":
            actions.extend(RECOMMENDED_ACTIONS.get(label, [])[:2])

    return {
        "summary": summary,
        "period_hours": period_hours,
        "generated_at": iso(datetime.now(timezone.utc).replace(tzinfo=None)),
        "totals": {
            "posts": len(posts),
            "threats": len(threats),
            "alerts": len(alerts),
            "critical_alerts": sum(1 for a in alerts if a.severity == "critical"),
            "avg_threat_score": round(mean(p.threat_score for p in posts), 1) if posts else 0,
        },
        "category_distribution": dict(label_counts),
        "language_distribution": dict(Counter(p.language for p in posts)),
        "platform_distribution": dict(Counter(p.platform for p in posts)),
        "top_threats": [post_to_dict(p, full=True) for p in top],
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
        Paragraph("SENTINEL — Threat Intelligence Report", h1),
        Paragraph(f"{report.title} • generated {p.get('generated_at', '')} • window {p.get('period_hours')}h", body),
        Spacer(1, 6 * mm),
        Paragraph("Executive Summary", h2),
        Paragraph(p.get("summary", ""), body),
        Spacer(1, 4 * mm),
        Paragraph("Classification Breakdown", h2),
    ]
    dist = p.get("category_distribution", {})
    table = Table([["Category", "Posts"]] + [[k, str(v)] for k, v in dist.items()], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F1420")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    flow.append(table)

    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph("Top Threats", h2))
    for t in p.get("top_threats", [])[:5]:
        flow.append(Paragraph(
            f"<b>[{t['threat_score']}] {t['threat_label']}</b> — {t['platform']} @{t['author_handle']} "
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
