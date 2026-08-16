# -*- coding: utf-8 -*-
"""Reference face gallery — the known-persons half of identification.

The suspect registry (`face_db`) answers "is this person on our records". This
module answers the other half of the same question: "do we know who this is at
all". It is a table of reference photographs — `ReferenceFace` — matched against
every face the forensics tools find.

Getting a person into it takes one action: drop a photo into the `pics/` folder.

    pics/
      Cristiano Ronaldo/          <- the folder name IS the person's name
        celebration.jpg
        portrait.webp
      Lionel Messi/
        messi.jpg
      narendra-modi.jpg           <- a loose file works too: "Narendra Modi"

That folder is an inbox, not the storage. Each new photo is embedded once and
then **written to the database** — the 128-d encoding, a face crop and a
downscaled copy of the photo itself. Which means the enrolled person survives
the file being deleted, the repository being re-cloned, or the console running
on a different machine against the same database; and it means no biometric
material is sitting in the source tree. Re-dropping a photo that is already
enrolled is a no-op: rows are deduplicated on the file's SHA-256.

Because the database is the record and the folder is only an inbox, deleting a
file does NOT delete the person. Removal is an explicit action — the gallery
panel's delete button, or `remove(id)` here.

Everything sealed: `encoding_enc`, `thumb_enc` and `image_enc` go through the
same Fernet key as the registry's templates. A face embedding is biometric data
wherever it lives, and this database is shared.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import threading
import time
from pathlib import Path

from sqlmodel import Session, select

from app.config import settings
from app.models import ReferenceFace
from app.models.models import utcnow
from app.security import crypto

log = logging.getLogger(__name__)

#: Same operating points as the suspect registry (`face_db`), on purpose: an
#: analyst reading "confirmed" should mean the same strength of evidence
#: whichever half of the pipeline produced it.
CONFIRMED_MAX = 0.45
PROBABLE_MAX = 0.52
POSSIBLE_MAX = 0.60

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

#: Longest edge of the copy kept in the database. Enough to show an analyst
#: which reference photo matched; far short of storing a 4K wallpaper in a
#: column, which is what the originals in an operator's folder tend to be.
_STORED_MAX_DIM = 768

#: How long the in-memory copy of the gallery is trusted before the table is
#: read again. One crowd photo produces a dozen probes, and each one must not
#: re-query (and re-decrypt) the whole gallery.
_CACHE_TTL = 20.0

#: Ingestion is at most this often per process. The scan itself is cheap when
#: nothing changed (a scandir plus a hash per file), but "cheap" times every
#: face of every upload is not free.
_SCAN_INTERVAL = 10.0

_lock = threading.RLock()
_cache: dict = {"at": 0.0, "rows": []}
_scan: dict = {"at": 0.0, "last": None}


def gallery_dir() -> Path:
    return Path(settings.FACE_GALLERY_DIR)


# ── naming ─────────────────────────────────────────────────────────────────

_SEP_RE = re.compile(r"[_\-.]+")
_NOISE_RE = re.compile(r"\b(?:img|image|photo|pic|dsc|screenshot|download|"
                       r"wallpaper|hd|4k|\d{3,}x\d{3,})\b", re.I)


def person_name(path: Path, root: Path) -> str:
    """The person a reference photo belongs to.

    A photo inside a folder takes the folder's name; a loose file takes its own
    stem. Separators become spaces and all-lowercase words are title-cased, so
    "cristiano-ronaldo" and "Cristiano Ronaldo" name the same person however the
    file arrived.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = Path(path.name)
    raw = rel.parts[0] if len(rel.parts) > 1 else rel.stem
    text = _NOISE_RE.sub(" ", _SEP_RE.sub(" ", raw))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = rel.stem or "Unnamed"
    return " ".join(w if any(c.isupper() for c in w) else w.capitalize()
                    for w in text.split())


def person_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# ── encoding one photo ─────────────────────────────────────────────────────

def _stored_copy(img) -> str:
    """A downscaled JPEG data-URI of the reference photo, for the gallery UI."""
    try:
        from PIL import Image, ImageOps

        try:
            img = ImageOps.exif_transpose(img) or img
        except Exception:
            pass
        small = img.convert("RGB")
        small.thumbnail((_STORED_MAX_DIM, _STORED_MAX_DIM), Image.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format="JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        log.warning("reference photo copy failed: %s", exc)
        return ""


def encode_photo(data: bytes) -> dict:
    """Embed the largest face in one reference photo, ready to store."""
    from PIL import Image

    from app.osint.face_db import crop_thumb
    from app.osint.face_detect import encode_reference

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            # deep=False: the CNN pass only fires when HOG finds nothing at all,
            # and on a folder of a hundred references that fallback is minutes
            # of CPU spent on photos that usually just are not portraits.
            result = encode_reference(img, deep=False)
            if result.get("ok"):
                result["thumb"] = crop_thumb(img, result["bounding_box"])
                result["image"] = _stored_copy(img)
    except Exception as exc:
        return {"ok": False, "error": f"could not be read as an image ({exc})"}
    return result


def enrol(session: Session, data: bytes, *, name: str, source_file: str = "",
          source: str = "upload") -> dict:
    """Add one reference photo for `name` to the gallery table."""
    sha = hashlib.sha256(data).hexdigest()
    existing = session.exec(
        select(ReferenceFace).where(ReferenceFace.image_sha256 == sha)
    ).first()
    if existing:
        return {"ok": True, "already_enrolled": True, "id": existing.id,
                "person_name": existing.person_name,
                "reason": f"Already enrolled as '{existing.person_name}'."}

    result = encode_photo(data)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "no face found"),
                "person_name": name, "source_file": source_file}

    row = ReferenceFace(
        person_name=name,
        person_key=person_key(name),
        image_sha256=sha,
        source_file=source_file,
        source=source,
        encoding_enc=crypto.seal_vector(result["encoding"]),
        thumb_enc=crypto.seal(result.get("thumb", "")),
        image_enc=crypto.seal(result.get("image", "")),
        quality=result.get("quality", {}),
        other_faces_ignored=result.get("other_faces_ignored", 0),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    _invalidate()
    return {"ok": True, "id": row.id, "person_name": name,
            "quality": row.quality}


def remove(session: Session, face_id: str) -> bool:
    row = session.get(ReferenceFace, face_id)
    if not row:
        return False
    session.delete(row)
    session.commit()
    _invalidate()
    return True


def rename(session: Session, face_id: str, name: str) -> bool:
    row = session.get(ReferenceFace, face_id)
    if not row:
        return False
    row.person_name = name
    row.person_key = person_key(name)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    _invalidate()
    return True


# ── ingesting the drop folder ──────────────────────────────────────────────

def sync(session: Session, *, force: bool = False) -> dict:
    """Ingest anything new in the `pics/` drop folder into the database.

    Deduplicated on file content, so this is safe to call as often as you like —
    a folder with nothing new in it costs one hash per file and no writes. Files
    already enrolled are left exactly where they are; the operator's folder is
    theirs, and this never deletes from it.
    """
    with _lock:
        now = time.monotonic()
        if not force and _scan["last"] is not None and (now - _scan["at"]) < _SCAN_INTERVAL:
            return _scan["last"]
        _scan["at"] = now

        root = gallery_dir()
        report = {"directory": str(root), "exists": root.is_dir(),
                  "scanned": 0, "enrolled": 0, "already": 0, "skipped": []}
        if not root.is_dir():
            _scan["last"] = report
            return report

        known = set(session.exec(select(ReferenceFace.image_sha256)).all())

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            report["scanned"] += 1
            try:
                data = path.read_bytes()
            except OSError as exc:
                report["skipped"].append({"file": path.name, "reason": str(exc)})
                continue
            sha = hashlib.sha256(data).hexdigest()
            if sha in known:
                report["already"] += 1
                continue

            rel = str(path.relative_to(root)).replace("\\", "/")
            name = person_name(path, root)
            res = enrol(session, data, name=name, source_file=rel,
                        source="gallery_folder")
            if res.get("ok") and not res.get("already_enrolled"):
                report["enrolled"] += 1
                known.add(sha)
                log.info("gallery: enrolled %s as '%s'", rel, name)
            elif res.get("ok"):
                report["already"] += 1
                known.add(sha)
            else:
                # Recorded rather than retried silently: a photo with no
                # detectable face will never enrol, and the operator needs to be
                # told which one and why instead of wondering why nothing
                # happened. It is re-attempted on the next forced sync, which
                # costs one detection pass on one file.
                report["skipped"].append({"file": rel, "person": name,
                                          "reason": res.get("error", "no face found")})
                log.info("gallery: %s skipped — %s", rel, res.get("error"))

        # Timed from the END of the scan, not the start: enrolling a folder of
        # new photos takes far longer than the interval, and stamping it up
        # front means the very next call rescans the folder it just finished.
        _scan["at"] = time.monotonic()
        _scan["last"] = report
        return report


# ── the in-memory working copy ─────────────────────────────────────────────

def _invalidate() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["rows"] = []
        _scan["at"] = 0.0


def _rows(session: Session) -> list[dict]:
    """Decrypted (name, embedding, thumb) triples for every active reference."""
    with _lock:
        now = time.monotonic()
        if _cache["rows"] and (now - _cache["at"]) < _CACHE_TTL:
            return _cache["rows"]

        out: list[dict] = []
        for r in session.exec(select(ReferenceFace)
                              .where(ReferenceFace.active == True)).all():  # noqa: E712
            try:
                vec = crypto.open_vector(r.encoding_enc)
            except RuntimeError:
                # Same policy as the registry: an undecryptable template is
                # excluded loudly rather than crashing the search, because a
                # silently smaller gallery means false negatives nobody notices.
                log.error("reference face %s cannot be decrypted; excluded from "
                          "matching", r.id)
                continue
            if len(vec) != 128:
                continue
            out.append({"id": r.id, "name": r.person_name,
                        "key": r.person_key or person_key(r.person_name),
                        "encoding": vec, "source_file": r.source_file,
                        "quality": r.quality or {}, "row": r})
        _cache["rows"] = out
        _cache["at"] = now
        return out


def _thumb(row: ReferenceFace) -> str:
    try:
        return crypto.open_(row.thumb_enc or "")
    except RuntimeError:
        return ""


# ── reporting ──────────────────────────────────────────────────────────────

def people(session: Session, *, with_photos: bool = False) -> list[dict]:
    """One entry per person in the gallery, newest reference first."""
    sync(session)
    by_person: dict[str, dict] = {}
    for r in _rows(session):
        row: ReferenceFace = r["row"]
        p = by_person.setdefault(r["key"], {"name": r["name"], "thumb": "",
                                            "photo_count": 0, "photos": []})
        p["photo_count"] += 1
        if not p["thumb"]:
            p["thumb"] = _thumb(row)
        if with_photos:
            try:
                image = crypto.open_(row.image_enc or "")
            except RuntimeError:
                image = ""
            p["photos"].append({
                "id": row.id,
                "source_file": row.source_file,
                "source": row.source,
                "quality": (row.quality or {}).get("score"),
                "thumb": _thumb(row),
                "image": image,
                "added_at": row.created_at.isoformat() + "Z",
            })
    return sorted(by_person.values(), key=lambda p: p["name"].lower())


def stats(session: Session) -> dict:
    scan = sync(session)
    rows = _rows(session)
    return {
        "directory": str(gallery_dir()),
        "exists": gallery_dir().is_dir(),
        "people": len({r["key"] for r in rows}),
        "photos": len(rows),
        "stored_in": "database",
        "last_scan": {"scanned": scan.get("scanned", 0),
                      "enrolled": scan.get("enrolled", 0)},
        "skipped": scan.get("skipped", []),
    }


def band_for(distance: float) -> str:
    if distance <= CONFIRMED_MAX:
        return "confirmed"
    if distance <= PROBABLE_MAX:
        return "probable"
    if distance <= POSSIBLE_MAX:
        return "possible"
    return "no_match"


def confidence_for(distance: float) -> float:
    """Same 0.75→0.25 mapping the registry uses, so the two are comparable."""
    return round(max(0.0, min(1.0, (0.75 - distance) / 0.5)), 3)


# ── matching ───────────────────────────────────────────────────────────────

def match(session: Session, encoding: list[float], *, top_k: int = 3) -> dict:
    """Search one probe embedding against every reference in the gallery.

    The closest person wins on their best photo — someone with five references
    is scored by whichever pose actually resembles the probe, not by their
    average — and nothing past the "possible" band is ever called an
    identification.
    """
    if not encoding or len(encoding) != 128:
        return {"identified": False, "searched": False, "candidates": [],
                "reason": "No usable embedding for this face."}

    try:
        sync(session)
        rows = _rows(session)
    except Exception as exc:
        log.warning("reference gallery unavailable: %s", exc)
        return {"identified": False, "searched": False, "candidates": [],
                "reason": f"Reference gallery unavailable: {exc}"}

    if not rows:
        d = gallery_dir()
        return {
            "identified": False, "searched": False, "people": 0, "photos": 0,
            "candidates": [],
            "reason": (f"No reference photos enrolled yet — drop photos into {d} "
                       f"(one folder per person) and they are read into the "
                       f"database automatically." if d.is_dir() else
                       f"The reference drop folder does not exist yet. Create {d} "
                       f"and put a folder of photos in it for each person."),
        }

    try:
        import numpy as np
    except Exception:
        return {"identified": False, "searched": False, "candidates": [],
                "reason": "numpy unavailable"}

    vectors = np.asarray([r["encoding"] for r in rows], dtype="float64")
    dists = np.linalg.norm(vectors - np.asarray(encoding, dtype="float64"), axis=1)

    best: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for r, d in zip(rows, dists):
        d = float(d)
        counts[r["key"]] = counts.get(r["key"], 0) + 1
        cur = best.get(r["key"])
        if cur is None or d < cur["distance"]:
            best[r["key"]] = {"name": r["name"], "distance": d,
                              "file": r["source_file"], "row": r["row"]}

    ranked = sorted(best.items(), key=lambda kv: kv[1]["distance"])[:max(1, top_k)]
    candidates = [{
        "name": v["name"],
        "distance": round(v["distance"], 4),
        "confidence": confidence_for(v["distance"]),
        "band": band_for(v["distance"]),
        "matched_photo": v["file"],
        "thumb": _thumb(v["row"]),
        "reference_photos": counts.get(k, 1),
    } for k, v in ranked]

    top = candidates[0]
    identified = top["band"] in ("confirmed", "probable")
    # Two different people this close means the photo does not separate them.
    ambiguous = (len(candidates) > 1
                 and candidates[1]["distance"] - top["distance"] < 0.06
                 and candidates[1]["band"] != "no_match")

    return {
        "identified": identified and not ambiguous,
        "searched": True,
        "ambiguous": ambiguous,
        "match": top if identified or top["band"] == "possible" else None,
        "candidates": [c for c in candidates if c["band"] != "no_match"],
        "people": len(counts),
        "photos": len(rows),
        "reason": (
            f"Two people in the gallery match this face almost equally well "
            f"({candidates[0]['name']} and {candidates[1]['name']}) — add a "
            f"clearer reference photo for each."
            if ambiguous else
            f"Matched {top['name']} at distance {top['distance']} ({top['band']}), "
            f"against {top['reference_photos']} reference photo(s)."
            if identified else
            f"Closest is {top['name']} at distance {top['distance']} — below the "
            f"identification threshold, treat as a resemblance only."
            if top["band"] == "possible" else
            f"No one in the reference gallery ({len(counts)} people, {len(rows)} "
            f"photos) matches this face."
        ),
    }
