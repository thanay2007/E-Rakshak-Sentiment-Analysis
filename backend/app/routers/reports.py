"""Reports: list, generate (JSON + PDF), download."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import col, select

from app.database import session_scope
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
def list_reports() -> list[dict]:
    with session_scope() as s:
        rows = s.exec(select(Report).order_by(col(Report.created_at).desc()).limit(50)).all()
        return [_report_dict(r, with_payload=False) for r in rows]


@router.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    with session_scope() as s:
        r = s.get(Report, report_id)
        if not r:
            raise HTTPException(404, "Report not found")
        return _report_dict(r)


@router.post("/reports/generate")
def create_report(req: ReportRequest) -> dict:
    report = generate_report(title=req.title, period_hours=req.period_hours, kind=req.kind)
    return _report_dict(report)


@router.get("/reports/{report_id}/download")
def download_report(report_id: str):
    with session_scope() as s:
        r = s.get(Report, report_id)
        if not r:
            raise HTTPException(404, "Report not found")
        if not r.pdf_path or not Path(r.pdf_path).exists():
            raise HTTPException(404, "PDF not available for this report")
        return FileResponse(r.pdf_path, media_type="application/pdf",
                            filename=f"SENTINEL_{r.kind}_{r.id}.pdf")
