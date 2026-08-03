"""Alerts: list + acknowledge/escalate workflow. Escalation also files an
escalation report built from the alert's post evidence."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from app.database import get_session
from app.security.deps import require_supervisor
from app.models import Alert, Post, Report, User
from app.services.report_service import escalation_template
from app.services.serializers import alert_to_dict

router = APIRouter()


@router.get("/alerts")
def list_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session)
) -> list[dict]:
    stmt = select(Alert).order_by(col(Alert.created_at).desc()).limit(limit)
    if status:
        stmt = stmt.where(Alert.status == status)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    return [alert_to_dict(a) for a in session.exec(stmt).all()]


from app.services.audit import log_action

def _set_status(alert_id: str, status: str, session: Session) -> dict:
    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.status = status
    alert.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    report_id = None
    if status == "escalated":
        post = session.get(Post, alert.post_id)
        if post and not alert.escalation:
            alert.escalation = escalation_template(post)
        report = Report(
            title=f"Escalation — {alert.title}",
            kind="escalation", period_hours=0,
            payload={"alert": alert_to_dict(alert), "escalation": alert.escalation},
        )
        session.add(report)
        session.flush()
        report_id = report.id
        log_action(session, "alert_escalated", alert_id, {"report_id": report_id})
    else:
        log_action(session, f"alert_{status}", alert_id)

    session.add(alert)
    session.commit()
    session.refresh(alert)
    result = alert_to_dict(alert)
    if report_id:
        result["escalation_report_id"] = report_id
    return result


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, session: Session = Depends(get_session)) -> dict:
    return _set_status(alert_id, "acknowledged", session)


@router.post("/alerts/{alert_id}/escalate")
def escalate(alert_id: str, session: Session = Depends(get_session),
             _: User = Depends(require_supervisor)) -> dict:
    """Supervisor+. Escalation generates an official report and is the point at
    which this system's output becomes an action taken in someone's name."""
    return _set_status(alert_id, "escalated", session)

