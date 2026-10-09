"""Authenticated manual lookup of visibly fictional demo records."""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import Session, select

from app.database import get_session
from app.models.demo_directory import DEMO_LABEL, DemoDirectoryProfile

router = APIRouter()


def _get(profile_id: str, session: Session) -> DemoDirectoryProfile:
    profile = session.get(DemoDirectoryProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "Demo profile not found")
    return profile


def _serialize(profile: DemoDirectoryProfile) -> dict:
    return {
        "id": profile.id, "full_name": profile.full_name,
        "role": profile.role, "bio": profile.bio,
        "is_fictional": True, "demo_label": DEMO_LABEL,
        "selection_method": "manual",
        "image_url": f"/api/demo-directory/{profile.id}/image",
        "image_alt": profile.image_alt,
        "image_source": profile.image_source,
        "image_prompt": profile.image_prompt,
        "case_history": [
            {**case, "is_fictional": True, "demo_label": DEMO_LABEL}
            for case in profile.case_history
        ],
    }


@router.get("/demo-directory")
def list_profiles(q: str = Query(default="", max_length=100),
                  session: Session = Depends(get_session)) -> dict:
    # The directory contains three demo records. Literal substring search
    # avoids treating user-entered SQL LIKE wildcards as a broad search.
    profiles = session.exec(select(DemoDirectoryProfile).order_by(DemoDirectoryProfile.full_name)).all()
    needle = q.strip().casefold()
    return {"demo_label": DEMO_LABEL, "is_fictional": True,
            "profiles": [_serialize(p) for p in profiles
                         if needle in p.full_name.casefold() or needle in p.id.casefold()]}


@router.get("/demo-directory/{profile_id}")
def get_profile(profile_id: str, session: Session = Depends(get_session)) -> dict:
    return _serialize(_get(profile_id, session))


@router.get("/demo-directory/{profile_id}/image")
def get_image(profile_id: str, session: Session = Depends(get_session)) -> Response:
    profile = _get(profile_id, session)
    return Response(profile.image_png, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "X-Demo-Data": "synthetic",
    })
