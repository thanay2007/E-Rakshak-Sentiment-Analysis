# -*- coding: utf-8 -*-
"""Facial identification endpoints — search, registry management, dossiers.

Two flows live here:

  search      an analyst uploads evidence; every face is detected, quality-
              graded, matched 1:N against the suspect registry, and each
              confirmed identity is returned with its full record, social
              accounts, monitored posts and linked alerts.

  registry    CRUD over the `Suspect` records plus reference-photo enrolment.
              A record with no reference photo can never be matched — enrolment
              is what turns a paper record into a searchable one.

Every search and every registry mutation is written to the AuditLog, and
searches additionally get a FaceSearchLog row carrying the probe's hash and the
distances it returned, so a match can be defended after the fact.
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, col, or_, select

from app.database import get_session
from app.models import FaceSearchLog, Suspect, User
from app.models.models import utcnow
from app.osint import face_db
from app.osint.face_db import RECORD_TYPES, RISK_LEVELS, STATUSES
from app.osint.face_detect import encode_reference, engine_status
from app.osint.face_intel import build_identity_dossier, identify_faces
from app.osint.image_analysis import analyze_image
from app.schemas import SuspectCreate, SuspectUpdate
from app.security.deps import require_supervisor
from app.security.ratelimit import Expensive
from app.services.audit import log_action, log_action_strict
from app.services.serializers import iso

router = APIRouter(prefix="/faces")

_MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _open_image(data: bytes):
    from PIL import Image
    import io

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception as exc:
        raise HTTPException(400, f"Could not decode that image: {exc}")


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, "File too large (max 25 MB).")
    return data


def _get(session: Session, suspect_id: str) -> Suspect:
    s = session.get(Suspect, suspect_id)
    if not s:
        raise HTTPException(404, "No such record in the suspect registry.")
    return s


def _validate(record_type: str | None, risk_level: str | None, status: str | None) -> None:
    if record_type is not None and record_type not in RECORD_TYPES:
        raise HTTPException(422, f"record_type must be one of {sorted(RECORD_TYPES)}")
    if risk_level is not None and risk_level not in RISK_LEVELS:
        raise HTTPException(422, f"risk_level must be one of {sorted(RISK_LEVELS)}")
    if status is not None and status not in STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")


# ── engine ─────────────────────────────────────────────────────────────────

@router.get("/engine")
def face_engine(session: Session = Depends(get_session)) -> dict:
    """Whether the biometric stack is usable, and how big the registry is."""
    rows = session.exec(select(Suspect).where(Suspect.active == True)).all()  # noqa: E712
    enrolled = [s for s in rows if (s.face_templates or [])]
    return {
        **engine_status(),
        "thresholds": {"confirmed": face_db.CONFIRMED_MAX,
                       "probable": face_db.PROBABLE_MAX,
                       "possible": face_db.POSSIBLE_MAX},
        "registry": {
            "active_records": len(rows),
            "enrolled_records": len(enrolled),
            "templates": sum(len(s.face_templates or []) for s in enrolled),
            "unenrolled_records": len(rows) - len(enrolled),
        },
    }


# ── search ─────────────────────────────────────────────────────────────────

@router.post("/search", dependencies=[Expensive])
async def face_search(file: UploadFile = File(...), deep: bool = False,
                      dossier: bool = True,
                      session: Session = Depends(get_session)) -> dict:
    """Identify every face in an uploaded image against the registry.

    `deep`    also run the CNN detector when the fast passes find nobody.
    `dossier` expand each identified person's handles with live cross-platform
              enumeration (slower; set false for a fast look-up).
    """
    data = await _read_upload(file)
    analysis = analyze_image(data, filename=file.filename or "", deep_faces=deep)
    if analysis.get("media_type") != "image":
        raise HTTPException(400, "Face search needs an image "
                                 f"(got {analysis.get('media_type', 'unknown')}).")

    identification = await identify_faces(session, analysis, deep=dossier,
                                          filename=file.filename or "")
    # Strict: a biometric search that ran without leaving a record is worse than
    # one that failed. If the log cannot be written, the caller gets the error.
    log_action_strict(session, "face_search", analysis.get("sha256", "")[:16],
                      {"faces": identification["faces_detected"],
                       "identified": identification["identified"],
                       "filename": file.filename})
    return {"analysis": analysis, "identification": identification}


@router.get("/searches")
def recent_searches(limit: int = 25, session: Session = Depends(get_session)) -> list[dict]:
    """Chain-of-custody log of biometric queries."""
    rows = session.exec(
        select(FaceSearchLog).order_by(col(FaceSearchLog.created_at).desc())
        .limit(max(1, min(limit, 200)))
    ).all()
    return [{"id": r.id, "image_sha256": r.image_sha256, "filename": r.filename,
             "faces_detected": r.faces_detected, "identified_count": r.identified_count,
             "results": r.results or [], "created_at": iso(r.created_at)} for r in rows]


# ── registry CRUD ──────────────────────────────────────────────────────────

@router.get("/suspects")
def list_suspects(q: str = "", record_type: str = "", enrolled_only: bool = False,
                  include_inactive: bool = False,
                  session: Session = Depends(get_session)) -> list[dict]:
    stmt = select(Suspect)
    if not include_inactive:
        stmt = stmt.where(Suspect.active == True)  # noqa: E712
    if record_type:
        stmt = stmt.where(Suspect.record_type == record_type)
    if q:
        needle = f"%{q.lower()}%"
        stmt = stmt.where(or_(col(Suspect.full_name).ilike(needle),
                              col(Suspect.last_known_location).ilike(needle),
                              col(Suspect.notes).ilike(needle)))
    rows = session.exec(stmt.order_by(col(Suspect.created_at).desc())).all()
    out = [face_db.to_dict(s) for s in rows]
    if enrolled_only:
        out = [d for d in out if d["enrolled_faces"]]
    if q:  # aliases live in a JSON column — filter those in Python
        needle = q.lower()
        out = [d for d in out
               if needle in d["full_name"].lower()
               or needle in (d["last_known_location"] or "").lower()
               or needle in (d["notes"] or "").lower()
               or any(needle in a.lower() for a in d["aliases"])
               or any(needle in (h.get("handle") or "").lower() for h in d["social_handles"])]
    return out


@router.post("/suspects", status_code=201)
def create_suspect(body: SuspectCreate, session: Session = Depends(get_session)) -> dict:
    if not body.full_name.strip():
        raise HTTPException(422, "full_name is required.")
    _validate(body.record_type, body.risk_level, body.status)
    data = body.model_dump()
    data["charges"] = [c for c in data.get("charges", [])]
    data["social_handles"] = [h for h in data.get("social_handles", [])]
    s = Suspect(**data, source="analyst")
    session.add(s)
    session.commit()
    session.refresh(s)
    log_action(session, "face_registry_create", s.id, {"name": s.full_name})
    return face_db.to_dict(s)


@router.get("/suspects/{suspect_id}")
def get_suspect(suspect_id: str, session: Session = Depends(get_session)) -> dict:
    return face_db.to_dict(_get(session, suspect_id))


@router.patch("/suspects/{suspect_id}")
def update_suspect(suspect_id: str, patch: SuspectUpdate,
                   session: Session = Depends(get_session)) -> dict:
    s = _get(session, suspect_id)
    data = patch.model_dump(exclude_none=True)
    _validate(data.get("record_type"), data.get("risk_level"), data.get("status"))
    for k, v in data.items():
        setattr(s, k, v)
    s.updated_at = utcnow()
    session.add(s)
    session.commit()
    session.refresh(s)
    log_action(session, "face_registry_update", s.id, {"fields": sorted(data)})
    return face_db.to_dict(s)


@router.delete("/suspects/{suspect_id}", status_code=204)
def delete_suspect(suspect_id: str, session: Session = Depends(get_session),
                   _: User = Depends(require_supervisor)) -> None:
    """Supervisor+. Destroys a criminal record and its biometric templates —
    irreversible, and logged strictly so the deletion itself is on record."""
    s = _get(session, suspect_id)
    log_action_strict(session, "face_registry_delete", s.id,
                      {"name": s.full_name, "case_ids": s.case_ids,
                       "templates": len(s.face_templates or [])})
    session.delete(s)
    session.commit()


# ── enrolment ──────────────────────────────────────────────────────────────

@router.post("/suspects/{suspect_id}/photo", status_code=201)
async def enroll_photo(suspect_id: str, file: UploadFile = File(...),
                       session: Session = Depends(get_session)) -> dict:
    """Attach a reference photo to a record, making it searchable.

    Enrol several photos per person across different angles and lighting — that
    is what lifts recall on real, badly-lit evidence.
    """
    s = _get(session, suspect_id)
    data = await _read_upload(file)
    img = _open_image(data)

    ref = encode_reference(img)
    if not ref.get("ok"):
        raise HTTPException(422, ref.get("error") or "Could not enrol that photo.")

    thumb = face_db.crop_thumb(img, ref["bounding_box"])
    added = face_db.add_template(session, s, encoding=ref["encoding"],
                                 quality=ref["quality"],
                                 source=file.filename or "upload", thumb=thumb)
    if not added.get("ok"):
        raise HTTPException(409, added.get("error") or "Could not add that template.")

    log_action(session, "face_registry_enroll", s.id,
               {"name": s.full_name, "quality": ref["quality"]["score"]})
    return {
        **added,
        "quality": ref["quality"],
        "other_faces_ignored": ref.get("other_faces_ignored", 0),
        "suspect": face_db.to_dict(s),
    }


@router.delete("/suspects/{suspect_id}/photo/{template_id}", status_code=204)
def delete_photo(suspect_id: str, template_id: str,
                 session: Session = Depends(get_session),
                 _: User = Depends(require_supervisor)) -> None:
    """Supervisor+. Removing the last template makes the record unmatchable."""
    s = _get(session, suspect_id)
    if not face_db.remove_template(session, s, template_id):
        raise HTTPException(404, "No such reference photo on this record.")
    log_action_strict(session, "face_registry_unenroll", s.id, {"template": template_id})


@router.post("/enroll", status_code=201)
async def enroll_new(file: UploadFile = File(...), full_name: str = Form(...),
                     record_type: str = Form("person_of_interest"),
                     risk_level: str = Form("medium"),
                     status: str = Form("under_investigation"),
                     aliases: str = Form(""), case_ids: str = Form(""),
                     jurisdiction: str = Form(""), last_known_location: str = Form(""),
                     notes: str = Form(""), social_handles: str = Form(""),
                     session: Session = Depends(get_session)) -> dict:
    """Create a record and enrol its first reference photo in one request.

    `aliases`, `case_ids` and `social_handles` are comma-separated; a handle may
    be written `platform:handle` (e.g. `X:desh_sachai_4471`) to record which
    platform it belongs to.
    """
    if not full_name.strip():
        raise HTTPException(422, "full_name is required.")
    _validate(record_type, risk_level, status)

    data = await _read_upload(file)
    img = _open_image(data)
    ref = encode_reference(img)
    if not ref.get("ok"):
        raise HTTPException(422, ref.get("error") or "Could not enrol that photo.")

    def split(raw: str) -> list[str]:
        return [x.strip() for x in raw.split(",") if x.strip()]

    handles = []
    for raw in split(social_handles):
        platform, _, handle = raw.rpartition(":")
        handles.append({"platform": platform.strip(), "handle": handle.strip().lstrip("@"),
                        "url": "", "note": ""})

    s = Suspect(
        full_name=full_name.strip(), aliases=split(aliases), record_type=record_type,
        risk_level=risk_level, status=status, case_ids=split(case_ids),
        jurisdiction=jurisdiction.strip(), last_known_location=last_known_location.strip(),
        notes=notes.strip(), social_handles=handles, source="analyst",
    )
    session.add(s)
    session.commit()
    session.refresh(s)

    thumb = face_db.crop_thumb(img, ref["bounding_box"])
    face_db.add_template(session, s, encoding=ref["encoding"], quality=ref["quality"],
                         source=file.filename or "upload", thumb=thumb)
    log_action(session, "face_registry_enroll_new", s.id,
               {"name": s.full_name, "quality": ref["quality"]["score"]})
    return {"ok": True, "quality": ref["quality"],
            "other_faces_ignored": ref.get("other_faces_ignored", 0),
            "suspect": face_db.to_dict(s)}


# ── dossier ────────────────────────────────────────────────────────────────

@router.get("/suspects/{suspect_id}/dossier", dependencies=[Expensive])
async def suspect_dossier(suspect_id: str, deep: bool = True,
                          session: Session = Depends(get_session)) -> dict:
    """Everything the system knows about a person: record, socials, posts,
    alerts and a merged timeline."""
    s = _get(session, suspect_id)
    log_action(session, "face_dossier", s.id, {"name": s.full_name})
    return await build_identity_dossier(session, s, deep=deep)
