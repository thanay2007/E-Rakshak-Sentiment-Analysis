# -*- coding: utf-8 -*-
"""Suspect registry — enrolment and 1:N biometric matching.

This is the "is this person on record" half of the identification pipeline.
`face_detect` turns evidence into 128-d embeddings; this module compares them
against the reference templates enrolled for each `Suspect` row and returns the
record when the distance is small enough to stand behind.

Matching policy (deliberately conservative — a false positive here is an
accusation against a real person):

  distance ≤ 0.45   confirmed   the record is asserted and the dossier is pulled
  distance ≤ 0.52   probable    asserted, flagged for analyst confirmation
  distance ≤ 0.60   possible    returned as a CANDIDATE only — never as an
                                identification, and no dossier is auto-pulled
  distance  > 0.60  no match

dlib's own recommended operating point is 0.6; we sit below it because the
evidence here is compressed social-media media rather than controlled captures.
Every result carries its raw distance so an analyst sees the actual evidence
strength rather than a laundered percentage.

Nothing in this module fabricates a record: an unenrolled face returns "no
match" and the registry starts empty apart from clearly-labelled demo entries.
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import datetime

from sqlmodel import Session, select

from app.models import Suspect
from app.models.models import utcnow
from app.security import crypto

log = logging.getLogger(__name__)

CONFIRMED_MAX = 0.45
PROBABLE_MAX = 0.52
POSSIBLE_MAX = 0.60

RECORD_TYPES = {"criminal", "wanted", "person_of_interest", "missing", "cleared"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
STATUSES = {"at_large", "in_custody", "on_bail", "convicted", "acquitted",
            "under_investigation", "cleared"}


def band_for(distance: float) -> str:
    if distance <= CONFIRMED_MAX:
        return "confirmed"
    if distance <= PROBABLE_MAX:
        return "probable"
    if distance <= POSSIBLE_MAX:
        return "possible"
    return "no_match"


def confidence_for(distance: float) -> float:
    """Map a face distance to a 0-1 score.

    Linear from 0.75 (worthless) down to 0.25 (effectively identical) so the
    number tracks the underlying metric instead of flattering it.
    """
    return round(max(0.0, min(1.0, (0.75 - distance) / 0.5)), 3)


# ── thumbnails ─────────────────────────────────────────────────────────────

def crop_thumb(img, box: dict, *, size: int = 160, pad: float = 0.35) -> str:
    """Crop a face (with headroom) to a small JPEG data-URI for the registry UI."""
    try:
        from PIL import Image, ImageOps

        try:
            img = ImageOps.exif_transpose(img) or img
        except Exception:
            pass
        img = img.convert("RGB")
        w, h = img.size
        bw, bh = box["right"] - box["left"], box["bottom"] - box["top"]
        px, py = int(bw * pad), int(bh * pad)
        crop = img.crop((max(0, box["left"] - px), max(0, box["top"] - py),
                         min(w, box["right"] + px), min(h, box["bottom"] + py)))
        crop.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        log.warning("thumbnail failed: %s", exc)
        return ""


# ── matching ───────────────────────────────────────────────────────────────

def template_vector(t: dict) -> list[float]:
    """Plaintext embedding for one stored template.

    Reads `vector_enc` (sealed) or falls back to `vector` (written before
    encryption was enabled), so an existing database keeps working and rows
    upgrade to sealed form as they are re-enrolled.
    """
    if t.get("vector_enc"):
        return crypto.open_vector(t["vector_enc"])
    return [float(x) for x in (t.get("vector") or [])]


def _templates(session: Session) -> tuple[list, list]:
    """Load (suspect, template, vector) triples for every active enrolled record."""
    rows = session.exec(select(Suspect).where(Suspect.active == True)).all()  # noqa: E712
    pairs = []
    for s in rows:
        for t in (s.face_templates or []):
            try:
                vec = template_vector(t)
            except RuntimeError:
                # Undecryptable template: skip it rather than crash the whole
                # search, but say so — a silently smaller registry means false
                # negatives on identifications, which nobody would notice.
                log.error("suspect %s has a template that cannot be decrypted; "
                          "it is excluded from matching", s.id)
                continue
            if vec and len(vec) == 128:
                pairs.append((s, t, vec))
    return rows, pairs


def _distances(np, probe, vectors):
    """Euclidean distance from one probe embedding to every stored template."""
    return np.linalg.norm(np.asarray(vectors, dtype="float64")
                          - np.asarray(probe, dtype="float64"), axis=1)


def match_encoding(session: Session, encoding: list[float], *,
                   top_k: int = 3) -> dict:
    """Search one probe embedding against the whole registry.

    Returns the best match plus runners-up. `identified` is True only for the
    confirmed/probable bands — a "possible" hit is surfaced as a candidate the
    analyst must adjudicate, never as an identification.
    """
    try:
        import numpy as np
    except Exception:
        return {"identified": False, "reason": "numpy unavailable", "candidates": []}

    if not encoding or len(encoding) != 128:
        return {"identified": False, "reason": "No usable embedding for this face.",
                "candidates": []}

    rows, pairs = _templates(session)
    if not pairs:
        return {
            "identified": False,
            "candidates": [],
            "registry_size": len(rows),
            "reason": ("No reference photos are enrolled in the suspect registry yet — "
                       "add a reference photo to a record to enable identification."
                       if rows else
                       "The suspect registry is empty. Enrol records with reference "
                       "photos to enable identification."),
        }

    dists = _distances(np, encoding, [vec for _s, _t, vec in pairs])

    # best (smallest) distance per suspect — a record may hold several photos
    best: dict[str, dict] = {}
    for (suspect, template, _vec), d in zip(pairs, dists):
        d = float(d)
        cur = best.get(suspect.id)
        if cur is None or d < cur["distance"]:
            best[suspect.id] = {"suspect": suspect, "distance": d,
                                "template_id": template.get("id", ""),
                                "template_source": template.get("source", "")}

    ranked = sorted(best.values(), key=lambda r: r["distance"])[:max(1, top_k)]
    candidates = [{
        "suspect_id": r["suspect"].id,
        "full_name": r["suspect"].full_name,
        "record_type": r["suspect"].record_type,
        "risk_level": r["suspect"].risk_level,
        "status": r["suspect"].status,
        "photo_thumb": thumb_of(r["suspect"].photo_thumb),
        "distance": round(r["distance"], 4),
        "confidence": confidence_for(r["distance"]),
        "band": band_for(r["distance"]),
        "matched_template": r["template_id"],
        "template_source": r["template_source"],
    } for r in ranked]

    top = candidates[0]
    identified = top["band"] in ("confirmed", "probable")

    # A second record almost as close means the biometric evidence does not
    # separate them — say so rather than picking the marginally closer one.
    ambiguous = (len(candidates) > 1
                 and candidates[1]["distance"] - top["distance"] < 0.06
                 and candidates[1]["band"] != "no_match")

    return {
        "identified": identified and not ambiguous,
        "ambiguous": ambiguous,
        "match": top if identified or top["band"] == "possible" else None,
        "candidates": [c for c in candidates if c["band"] != "no_match"],
        "registry_size": len(rows),
        "templates_searched": len(pairs),
        "reason": (
            "Two records match this face almost equally well — biometric evidence "
            "alone cannot separate them; confirm manually."
            if ambiguous else
            f"Matched '{top['full_name']}' at distance {top['distance']} ({top['band']})."
            if identified else
            f"Closest record '{top['full_name']}' at distance {top['distance']} — "
            "below the identification threshold, treat as a lead only."
            if top["band"] == "possible" else
            "No record in the registry matches this face."
        ),
    }


# ── enrolment / CRUD ───────────────────────────────────────────────────────

def _new_template_id(suspect: Suspect) -> str:
    return f"tpl-{len(suspect.face_templates or []) + 1}-{int(datetime.now().timestamp())}"


def add_template(session: Session, suspect: Suspect, *, encoding: list[float],
                 quality: dict, source: str = "analyst upload",
                 thumb: str = "") -> dict:
    """Attach a reference embedding to a record.

    Near-duplicate templates (distance < 0.2 from one already stored) are
    rejected: they add matching cost without widening the pose/lighting
    coverage that actually improves recall.
    """
    try:
        import numpy as np

        existing = [v for v in (template_vector(t) for t in (suspect.face_templates or []))
                    if len(v) == 128]
        if existing:
            d = float(_distances(np, encoding, existing).min())
            if d < 0.2:
                return {"ok": False,
                        "error": f"A near-identical reference photo is already enrolled "
                                 f"(distance {round(d, 3)}). Add a photo from a different "
                                 f"angle or lighting instead."}
    except Exception:
        pass

    template = {
        "id": _new_template_id(suspect),
        # Sealed at rest. The plaintext `vector` key is deliberately absent so a
        # dump of the JSON column yields no usable biometric.
        "vector_enc": crypto.seal_vector(encoding),
        "quality": quality,
        "source": source,
        "thumb": crypto.seal(thumb),
        "added_at": utcnow().isoformat() + "Z",
    }
    # JSON columns need reassignment for SQLAlchemy to notice the mutation
    suspect.face_templates = list(suspect.face_templates or []) + [template]
    if thumb and not suspect.photo_thumb:
        suspect.photo_thumb = crypto.seal(thumb)
    suspect.updated_at = utcnow()
    session.add(suspect)
    session.commit()
    session.refresh(suspect)
    return {"ok": True, "template_id": template["id"],
            "templates": len(suspect.face_templates)}


def remove_template(session: Session, suspect: Suspect, template_id: str) -> bool:
    before = len(suspect.face_templates or [])
    suspect.face_templates = [t for t in (suspect.face_templates or [])
                              if t.get("id") != template_id]
    if len(suspect.face_templates) == before:
        return False
    suspect.updated_at = utcnow()
    session.add(suspect)
    session.commit()
    return True


def thumb_of(value: str) -> str:
    """Decrypt a stored thumbnail for display; never raises into a response."""
    try:
        return crypto.open_(value or "")
    except RuntimeError:
        log.error("stored thumbnail could not be decrypted")
        return ""


# Never serialised to a client: the embedding in either form. Ciphertext is
# still biometric material, and handing it out would defeat sealing it.
_SECRET_TEMPLATE_KEYS = {"vector", "vector_enc"}


def to_dict(s: Suspect, *, include_vectors: bool = False) -> dict:
    """Serialise a record. Embeddings are omitted by default — they are
    biometric data and the UI never needs the raw 128 floats."""
    return {
        "id": s.id,
        "full_name": s.full_name,
        "aliases": s.aliases or [],
        "record_type": s.record_type,
        "risk_level": s.risk_level,
        "status": s.status,
        "case_ids": s.case_ids or [],
        "charges": s.charges or [],
        "convictions": s.convictions,
        "jurisdiction": s.jurisdiction,
        "last_known_location": s.last_known_location,
        "wanted_since": s.wanted_since,
        "gender": s.gender,
        "age": s.age,
        "nationality": s.nationality,
        "identifying_marks": s.identifying_marks,
        "notes": s.notes,
        "social_handles": s.social_handles or [],
        "photo_thumb": thumb_of(s.photo_thumb),
        "source": s.source,
        "active": s.active,
        "enrolled_faces": len(s.face_templates or []),
        "face_templates": [
            {**{k: v for k, v in t.items() if k not in _SECRET_TEMPLATE_KEYS},
             "thumb": thumb_of(t.get("thumb", "")),
             **({"vector": template_vector(t)} if include_vectors else {})}
            for t in (s.face_templates or [])
        ],
        "created_at": s.created_at.isoformat() + "Z",
        "updated_at": s.updated_at.isoformat() + "Z",
    }
