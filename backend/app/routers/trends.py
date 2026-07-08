from fastapi import APIRouter, Query

from app.services.trend_service import get_trends

router = APIRouter()


@router.get("/trends")
def trends(hours: int = Query(24, ge=1, le=168)) -> dict:
    return get_trends(hours)
