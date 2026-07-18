from sqlmodel import Session
from app.models import AuditLog

def log_action(session: Session, action: str, target_id: str = "", details: dict = None) -> None:
    """Logs an analyst action to the database."""
    log_entry = AuditLog(
        action=action,
        target_id=target_id,
        details=details or {}
    )
    session.add(log_entry)
    session.commit()
