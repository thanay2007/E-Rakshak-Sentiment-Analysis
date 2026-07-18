"""Reports: list, generate (JSON + PDF), download."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, col, select

from app.database import get_session
from app.models import Report
from app.schemas import ReportRequest
from app.services.report_service import generate_report
from app.services.serializers import iso

router = APIRouter()


def _report_dict(r: Report, with_payload: bool = True) -> dict:
    d = {
        "id": r.id, "title": r.title, "kind": r.kind,
        "period_hours": r.period_hours, "created_at": iso(r.created_at),
        "has_pdf": bool(r.pdf_path),
    }
    if with_payload:
        d["payload"] = r.payload
    return d


@router.get("/reports")
def list_reports(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(Report).order_by(col(Report.created_at).desc()).limit(50)).all()
    return [_report_dict(r, with_payload=False) for r in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: str, session: Session = Depends(get_session)) -> dict:
    r = session.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return _report_dict(r)


@router.post("/reports/generate")
def create_report(req: ReportRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.audit import log_action
    report = generate_report(title=req.title, period_hours=req.period_hours, kind=req.kind)
    log_action(session, "report_generated", report.id, {"kind": req.kind, "period": req.period_hours})
    return _report_dict(report)

@router.post("/reports/briefing")
async def create_intelligence_briefing(req: ReportRequest, session: Session = Depends(get_session)) -> dict:
    from app.services.audit import log_action
    from app.services.groq_verifier import summarize_briefing
    report = generate_report(title=req.title, period_hours=req.period_hours, kind="intelligence_briefing")
    
    # generate LLM summary based on the payload's generic summary
    briefing_text = await summarize_briefing(report.payload["summary"])
    report.payload["summary"] = briefing_text
    
    # re-save payload
    session.add(report)
    session.commit()
    session.refresh(report)
    
    log_action(session, "briefing_generated", report.id, {"period": req.period_hours})
    return _report_dict(report)


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, session: Session = Depends(get_session)):
    from app.services.audit import log_action
    r = session.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    if not r.pdf_path or not Path(r.pdf_path).exists():
        raise HTTPException(404, "PDF not available for this report")
    log_action(session, "report_downloaded", report_id)
    return FileResponse(r.pdf_path, media_type="application/pdf",
                        filename=f"SENTINEL_{r.kind}_{r.id}.pdf")

