"""Alerts: list + acknowledge/escalate workflow. Escalation also files an
escalation report built from the alert's post evidence."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from app.database import session_scope
from app.models import Alert, Post, Report
from app.services.report_service import escalation_template
from app.services.serializers import alert_to_dict

router = APIRouter()


@router.get("/alerts")
def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    stmt = select(Alert).order_by(col(Alert.created_at).desc()).limit(limit)
    if status:
        stmt = stmt.where(Alert.status == status)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    with session_scope() as s:
        return [alert_to_dict(a) for a in s.exec(stmt).all()]


def _set_status(alert_id: str, status: str) -> dict:
    with session_scope() as s:
        alert = s.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")
        alert.status = status
        alert.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

        report_id = None
        if status == "escalated":
            post = s.get(Post, alert.post_id)
            if post and not alert.escalation:
                alert.escalation = escalation_template(post)
            report = Report(
                title=f"Escalation — {alert.title}",
                kind="escalation", period_hours=0,
                payload={"alert": alert_to_dict(alert), "escalation": alert.escalation},
            )
            s.add(report)
            s.flush()
            report_id = report.id

        s.add(alert)
        s.commit()
        s.refresh(alert)
        result = alert_to_dict(alert)
    if report_id:
        result["escalation_report_id"] = report_id
    return result


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str) -> dict:
    return _set_status(alert_id, "acknowledged")


@router.post("/alerts/{alert_id}/escalate")
def escalate(alert_id: str) -> dict:
    return _set_status(alert_id, "escalated")
