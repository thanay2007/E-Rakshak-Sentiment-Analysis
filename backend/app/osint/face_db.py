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

Those bands are the FALLBACK. Wherever both the probe and a template carry an
ArcFace embedding (`face_embed`), identity is decided on ArcFace cosine
similarity instead, with its own operating points (face_embed.CONFIRMED_MIN
etc.) — it is far better at "a different photo of the same person", which is
the case that matters. Results from either metric are ranked on the shared 0-1
confidence scale, and every result says which metric produced it and carries
the raw number, so an analyst sees the actual evidence strength rather than a
laundered percentage.

Nothing in this module fabricates a record: an unenrolled face returns "no
match" and the registry starts empty apart from clearly-labelled demo entries.
"""
from __future__ import annotations

import base64
import io
import logging
import threading
from datetime import datetime

from sqlmodel import Session, select

from app.models import Suspect
from app.models.models import utcnow
from app.osint import face_embed
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


#: Two candidates whose confidence is closer than this are not separated by the
#: evidence. 0.12 is the old 0.06 dlib-distance margin on the confidence scale.
AMBIGUITY_MARGIN = 0.12


def compare(encoding: list[float] | None, arcface: list[float] | None,
            ref_encoding: list[float] | None, ref_arcface: list[float] | None) -> dict | None:
    """Score one probe against one reference, on the best metric both share.

    Returns {metric, distance, similarity, band, confidence}, or None when the
    two have no embedding in common. `distance` is always present so existing
    readers keep working; for ArcFace it is the cosine distance (1 - sim).
    """
    if arcface and ref_arcface and len(arcface) == len(ref_arcface) == face_embed.DIM:
        sim = face_embed.similarity(arcface, ref_arcface)
        return {"metric": "arcface", "similarity": round(sim, 4),
                "distance": round(1.0 - sim, 4), "band": face_embed.band_for(sim),
                "confidence": face_embed.confidence_for(sim)}
    if encoding and ref_encoding and len(encoding) == len(ref_encoding) == 128:
        import numpy as np

        d = float(np.linalg.norm(np.asarray(encoding, dtype="float64")
                                 - np.asarray(ref_encoding, dtype="float64")))
        return {"metric": "dlib", "similarity": None, "distance": round(d, 4),
                "band": band_for(d), "confidence": confidence_for(d)}
    return None


def evidence_text(c: dict) -> str:
    """The raw number behind a result, named for the metric that produced it."""
    if c.get("metric") == "arcface":
        return f"ArcFace similarity {c['similarity']}"
    return f"distance {c['distance']}"


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
    """Load (suspect, template, dlib vector, arcface vector) for every active
    enrolled record."""
    rows = session.exec(select(Suspect).where(Suspect.active == True)).all()  # noqa: E712
    backfill_arcface(session, rows)
    pairs = []
    for s in rows:
        for t in (s.face_templates or []):
            try:
                vec = template_vector(t)
                arc = crypto.open_vector(t["arc_enc"]) if t.get("arc_enc") else None
            except RuntimeError:
                # Undecryptable template: skip it rather than crash the whole
                # search, but say so — a silently smaller registry means false
                # negatives on identifications, which nobody would notice.
                log.error("suspect %s has a template that cannot be decrypted; "
                          "it is excluded from matching", s.id)
                continue
            if (vec and len(vec) == 128) or arc:
                pairs.append((s, t, vec, arc))
    return rows, pairs


_backfill_lock = threading.Lock()
_backfill_tried: set[str] = set()


def backfill_arcface(session: Session, rows: list[Suspect] | None = None) -> int:
    """Give templates enrolled before ArcFace existed an ArcFace embedding.

    Only the face crop is stored for those, so that is what gets embedded — not
    as good as the original photo, which is why re-enrolling a clear photo is
    still worth doing, but far better than leaving the record on dlib. Each
    template is attempted once per process; one with no detectable face in its
    crop simply stays on dlib.
    """
    if not face_embed.available():
        return 0
    if rows is None:
        rows = session.exec(select(Suspect).where(Suspect.active == True)).all()  # noqa: E712
    done = 0
    with _backfill_lock:
        for s in rows:
            changed = False
            templates = []
            for t in (s.face_templates or []):
                key = f"{s.id}:{t.get('id')}"
                if t.get("arc_enc") or key in _backfill_tried:
                    templates.append(t)
                    continue
                _backfill_tried.add(key)
                vec = None
                try:
                    from PIL import Image

                    uri = thumb_of(t.get("thumb", ""))
                    if uri.startswith("data:image"):
                        raw = base64.b64decode(uri.split(",", 1)[1])
                        with Image.open(io.BytesIO(raw)) as img:
                            img.load()
                            vec = face_embed.embed_largest_face(img)
                except Exception as exc:
                    log.warning("ArcFace backfill of %s failed: %s", key, exc)
                if vec:
                    t = {**t, "arc_enc": crypto.seal_vector(vec)}
                    changed = True
                    done += 1
                templates.append(t)
            if changed:
                s.face_templates = templates
                session.add(s)
        if done:
            session.commit()
            log.info("ArcFace backfill: %d registry template(s) embedded", done)
    return done


def match_encoding(session: Session, encoding: list[float] | None, *,
                   arcface: list[float] | None = None, top_k: int = 3) -> dict:
    """Search one probe against the whole registry.

    Returns the best match plus runners-up. `identified` is True only for the
    confirmed/probable bands — a "possible" hit is surfaced as a candidate the
    analyst must adjudicate, never as an identification.
    """
    if not ((encoding and len(encoding) == 128) or arcface):
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

    # Best template per suspect — a record may hold several photos, and the one
    # whose pose/lighting resembles the probe is the one that should decide.
    best: dict[str, dict] = {}
    for suspect, template, vec, arc in pairs:
        c = compare(encoding, arcface, vec, arc)
        if c is None:
            continue
        cur = best.get(suspect.id)
        if cur is None or c["confidence"] > cur["confidence"]:
            best[suspect.id] = {**c, "suspect": suspect,
                                "template_id": template.get("id", ""),
                                "template_source": template.get("source", "")}

    if not best:
        return {"identified": False, "candidates": [], "registry_size": len(rows),
                "reason": "No enrolled template shares an embedding type with this face."}

    ranked = sorted(best.values(), key=lambda r: r["confidence"],
                    reverse=True)[:max(1, top_k)]
    candidates = [{
        "suspect_id": r["suspect"].id,
        "full_name": r["suspect"].full_name,
        "record_type": r["suspect"].record_type,
        "risk_level": r["suspect"].risk_level,
        "status": r["suspect"].status,
        "photo_thumb": thumb_of(r["suspect"].photo_thumb),
        "distance": r["distance"],
        "similarity": r["similarity"],
        "metric": r["metric"],
        "confidence": r["confidence"],
        "band": r["band"],
        "matched_template": r["template_id"],
        "template_source": r["template_source"],
    } for r in ranked]

    top = candidates[0]
    identified = top["band"] in ("confirmed", "probable")

    # A second record almost as close means the biometric evidence does not
    # separate them — say so rather than picking the marginally closer one.
    ambiguous = (len(candidates) > 1
                 and top["confidence"] - candidates[1]["confidence"] < AMBIGUITY_MARGIN
                 and candidates[1]["band"] != "no_match")

    return {
        "identified": identified and not ambiguous,
        "ambiguous": ambiguous,
        "match": top if identified or top["band"] == "possible" else None,
        "candidates": [c for c in candidates if c["band"] != "no_match"],
        "registry_size": len(rows),
        "templates_searched": len(pairs),
        "metric": top["metric"],
        "reason": (
            "Two records match this face almost equally well — biometric evidence "
            "alone cannot separate them; confirm manually."
            if ambiguous else
            f"Matched '{top['full_name']}' at {evidence_text(top)} ({top['band']})."
            if identified else
            f"Closest record '{top['full_name']}' at {evidence_text(top)} — "
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
                 thumb: str = "", arcface: list[float] | None = None) -> dict:
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
        **({"arc_enc": crypto.seal_vector(arcface)} if arcface else {}),
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
_SECRET_TEMPLATE_KEYS = {"vector", "vector_enc", "arc_enc"}


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
        "height_cm": s.height_cm,
        "occupation": s.occupation,
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
             "arcface": bool(t.get("arc_enc")),
             **({"vector": template_vector(t)} if include_vectors else {})}
            for t in (s.face_templates or [])
        ],
        "created_at": s.created_at.isoformat() + "Z",
        "updated_at": s.updated_at.isoformat() + "Z",
    }
