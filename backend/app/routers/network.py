from fastapi import APIRouter, Query

from app.services.network_service import get_network

router = APIRouter()


@router.get("/network")
def network(hours: int = Query(24, ge=1, le=168)) -> dict:
    return get_network(hours)
