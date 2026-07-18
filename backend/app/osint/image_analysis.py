# -*- coding: utf-8 -*-
"""Forensic analysis of an uploaded image (and best-effort for video).

Real, offline analysis — no external service:
  • format / dimensions / size
  • EXIF metadata: camera make+model, capture + edit timestamps, software,
    orientation, and GPS → decimal lat/lon (with a maps link)
  • perceptual fingerprints: 64-bit dHash + aHash (hex) for reverse lookup
  • manipulation signals: editor software tags, capture/edit-time mismatch,
    stripped metadata, screenshot markers — each with a plain-English reason

The perceptual hashes returned here are what media_intel uses to answer
"where else has this image appeared".
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime

try:
    from PIL import Image, ExifTags
    _PIL = True
except Exception:  # pragma: no cover - Pillow always present in this repo
    _PIL = False

_GPS_TAGS = {v: k for k, v in getattr(ExifTags, "GPSTAGS", {}).items()} if _PIL else {}
_TAGS = ExifTags.TAGS if _PIL else {}
_GPSTAGS = ExifTags.GPSTAGS if _PIL else {}

_EDITOR_SOFTWARE = ("photoshop", "gimp", "lightroom", "snapseed", "picsart",
                    "pixlr", "affinity", "canva", "facetune", "remini")
_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".3gp")


def _to_gray_matrix(img: "Image.Image", w: int, h: int) -> list[list[int]]:
    small = img.convert("L").resize((w, h), Image.BILINEAR)
    px = list(small.getdata())
    return [px[r * w:(r + 1) * w] for r in range(h)]


def _dhash(img: "Image.Image", size: int = 8) -> str:
    """Difference hash: compare each pixel to its right neighbour (9×8 grid)."""
    rows = _to_gray_matrix(img, size + 1, size)
    bits = 0
    for r in rows:
        for i in range(size):
            bits = (bits << 1) | (1 if r[i] < r[i + 1] else 0)
    return f"{bits:016x}"


def _ahash(img: "Image.Image", size: int = 8) -> str:
    """Average hash: each pixel brighter than the mean → 1."""
    rows = _to_gray_matrix(img, size, size)
    flat = [p for r in rows for p in r]
    avg = sum(flat) / len(flat)
    bits = 0
    for p in flat:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return f"{bits:016x}"


def _ratio(dms, ref) -> float | None:
    try:
        d, m, s = [float(x) for x in dms]
        val = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            val = -val
        return round(val, 6)
    except Exception:
        return None


def _parse_gps(gps: dict) -> dict | None:
    named = {_GPSTAGS.get(k, k): v for k, v in gps.items()}
    lat = _ratio(named.get("GPSLatitude"), named.get("GPSLatitudeRef"))
    lon = _ratio(named.get("GPSLongitude"), named.get("GPSLongitudeRef"))
    if lat is None or lon is None:
        return None
    out = {"latitude": lat, "longitude": lon,
           "maps_url": f"https://www.google.com/maps?q={lat},{lon}"}
    if "GPSAltitude" in named:
        try:
            out["altitude_m"] = round(float(named["GPSAltitude"]), 1)
        except Exception:
            pass
    return out


def _exif(img: "Image.Image") -> tuple[dict, dict | None]:
    try:
        raw = img._getexif() or {}
    except Exception:
        raw = {}
    if not raw:
        return {}, None
    named = {_TAGS.get(k, str(k)): v for k, v in raw.items()}
    gps = _parse_gps(named["GPSInfo"]) if isinstance(named.get("GPSInfo"), dict) else None

    def clean(v):
        if isinstance(v, bytes):
            return v.decode("utf-8", "ignore").strip("\x00").strip()
        return str(v).strip("\x00").strip()

    out = {}
    for key in ("Make", "Model", "Software", "DateTimeOriginal", "DateTime",
                "DateTimeDigitized", "LensModel", "Artist", "Copyright"):
        if key in named and clean(named[key]):
            out[key] = clean(named[key])
    if "Orientation" in named:
        out["Orientation"] = named["Orientation"]
    return out, gps


def _parse_dt(s: str) -> datetime | None:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None


def _manipulation_signals(exif: dict, gps, fmt: str, has_exif: bool) -> tuple[list[dict], int]:
    """Return (findings, integrity_score 0..100). Higher score = more trustworthy."""
    findings: list[dict] = []
    penalty = 0

    sw = (exif.get("Software") or "").lower()
    if any(e in sw for e in _EDITOR_SOFTWARE):
        findings.append({"level": "high",
                         "text": f"Edited with image software: {exif['Software']}"})
        penalty += 40

    orig = _parse_dt(exif.get("DateTimeOriginal", "")) if exif else None
    mod = _parse_dt(exif.get("DateTime", "")) if exif else None
    if orig and mod and abs((mod - orig).total_seconds()) > 60:
        findings.append({"level": "medium",
                         "text": f"File was modified after capture "
                                 f"(shot {orig:%Y-%m-%d %H:%M}, last saved {mod:%Y-%m-%d %H:%M})"})
        penalty += 22

    if not has_exif and fmt in ("JPEG", "MPO"):
        findings.append({"level": "medium",
                         "text": "No camera metadata — image was re-saved, screenshotted "
                                 "or scrubbed (common for forwarded / downloaded media)"})
        penalty += 18
    if not has_exif and fmt == "PNG":
        findings.append({"level": "low",
                         "text": "PNG with no camera metadata — typically a screenshot or "
                                 "graphic, not an original photograph"})
        penalty += 8

    if exif and not gps and exif.get("Make"):
        findings.append({"level": "low",
                         "text": "Camera metadata present but GPS stripped — location "
                                 "may have been removed before sharing"})
        penalty += 4

    if not findings:
        findings.append({"level": "ok",
                         "text": "No obvious manipulation markers; metadata is internally consistent"})
    return findings, max(0, 100 - penalty)


def analyze_image(data: bytes, filename: str = "") -> dict:
    """Analyze raw image bytes. Returns a JSON-safe forensic report."""
    sha = hashlib.sha256(data).hexdigest()
    name_l = (filename or "").lower()
    base = {
        "filename": filename or "upload",
        "size_bytes": len(data),
        "sha256": sha,
    }

    if any(name_l.endswith(ext) for ext in _VIDEO_EXT):
        return {**base, "media_type": "video",
                "note": "Video frame-level forensics require server-side decoding "
                        "(ffmpeg) — not enabled in this build. Metadata hash and "
                        "reverse-source matching still apply to the file as a whole.",
                "perceptual_hash": None, "average_hash": None,
                "exif": {}, "gps": None,
                "manipulation": {"integrity_score": None, "findings": []}}

    if not _PIL:
        return {**base, "media_type": "image", "error": "Pillow not available"}

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        return {**base, "media_type": "unknown",
                "error": f"Could not decode image: {exc}"}

    fmt = img.format or "?"
    exif, gps = _exif(img)
    findings, integrity = _manipulation_signals(exif, gps, fmt, bool(exif))

    camera = None
    if exif.get("Make") or exif.get("Model"):
        camera = " ".join(x for x in (exif.get("Make"), exif.get("Model")) if x).strip()

    # Face Recognition
    faces_detected = 0
    face_matches = []
    try:
        import face_recognition
        import numpy as np
        
        # Convert PIL Image to RGB numpy array for face_recognition
        rgb_img = img.convert('RGB')
        img_np = np.array(rgb_img)
        
        face_locations = face_recognition.face_locations(img_np)
        faces_detected = len(face_locations)
        
        # If we had a local suspect database, we would encode and compare here:
        # encodings = face_recognition.face_encodings(img_np, face_locations)
        # matches = face_recognition.compare_faces(known_suspect_encodings, encodings[0])
        # For now, just return the count and bounding boxes.
        if faces_detected > 0:
            for top, right, bottom, left in face_locations:
                face_matches.append({
                    "bounding_box": {"top": int(top), "right": int(right), "bottom": int(bottom), "left": int(left)},
                    "matched_suspect": None, # Placeholder for cross-referencing logic
                    "confidence": None
                })
    except ImportError:
        pass # face_recognition not installed
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Face recognition error: {e}")

    return {
        **base,
        "media_type": "image",
        "format": fmt,
        "width": img.width,
        "height": img.height,
        "megapixels": round(img.width * img.height / 1e6, 2),
        "mode": img.mode,
        "perceptual_hash": _dhash(img),
        "average_hash": _ahash(img),
        "camera": camera,
        "captured_at": exif.get("DateTimeOriginal"),
        "software": exif.get("Software"),
        "exif": exif,
        "gps": gps,
        "manipulation": {"integrity_score": integrity, "findings": findings},
        "forensics": {
            "faces_detected": faces_detected,
            "face_matches": face_matches
        }
    }
