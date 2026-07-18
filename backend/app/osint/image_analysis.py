# -*- coding: utf-8 -*-
"""Forensic analysis of uploaded media — images AND videos.

Real, offline analysis — no external service:
  images:
  • format / dimensions / size
  • EXIF metadata: camera make+model, capture + edit timestamps, software,
    orientation, and GPS → decimal lat/lon (with a maps link)
  • perceptual fingerprints: 64-bit dHash + aHash (hex) for reverse lookup
  • manipulation signals: editor software tags, capture/edit-time mismatch,
    stripped metadata, screenshot markers — each with a plain-English reason
  videos (MP4/MOV/3GP family, parsed with a pure-Python box walker — no ffmpeg):
  • container brand, duration, resolution, codec, estimated bitrate
  • creation/modification timestamps from the container, with the same
    scrubbed/re-encoded/edited-after-capture signals as images

The perceptual hashes returned here are what media_intel uses to answer
"where else has this media appeared".
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


# ── MP4/MOV box parsing (pure Python — no ffmpeg dependency) ──────────────
_MP4_EPOCH_OFFSET = 2082844800  # seconds between 1904-01-01 (MP4 epoch) and 1970-01-01
_CODEC_NAMES = {"avc1": "H.264/AVC", "avc3": "H.264/AVC", "hvc1": "H.265/HEVC",
                "hev1": "H.265/HEVC", "vp09": "VP9", "av01": "AV1", "mp4v": "MPEG-4"}


def _iter_boxes(data: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        btype = data[pos + 4:pos + 8]
        header = 8
        if size == 1 and pos + 16 <= end:
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield btype, pos + header, min(pos + size, end)
        pos += size


def _find_box(data: bytes, path: list[bytes], start: int = 0, end: int | None = None):
    """Descend a box path like [b'moov', b'mvhd']; return (body_start, body_end)."""
    end = len(data) if end is None else end
    for btype, bs, be in _iter_boxes(data, start, end):
        if btype == path[0]:
            if len(path) == 1:
                return bs, be
            return _find_box(data, path[1:], bs, be)
    return None


def _mp4_time(raw: int) -> datetime | None:
    if raw <= _MP4_EPOCH_OFFSET:  # zero/epoch → no real timestamp recorded
        return None
    try:
        return datetime.utcfromtimestamp(raw - _MP4_EPOCH_OFFSET)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_mp4(data: bytes) -> dict:
    out: dict = {}
    ftyp = _find_box(data, [b"ftyp"])
    if ftyp:
        out["brand"] = data[ftyp[0]:ftyp[0] + 4].decode("ascii", "ignore").strip()

    mvhd = _find_box(data, [b"moov", b"mvhd"])
    if mvhd:
        b = data[mvhd[0]:mvhd[1]]
        version = b[0]
        if version == 1 and len(b) >= 32:
            created = int.from_bytes(b[4:12], "big")
            modified = int.from_bytes(b[12:20], "big")
            timescale = int.from_bytes(b[20:24], "big")
            duration = int.from_bytes(b[24:32], "big")
        elif len(b) >= 24:
            created = int.from_bytes(b[4:8], "big")
            modified = int.from_bytes(b[8:12], "big")
            timescale = int.from_bytes(b[12:16], "big")
            duration = int.from_bytes(b[16:20], "big")
        else:
            return out
        if timescale:
            out["duration_s"] = round(duration / timescale, 1)
        out["created_at"] = _mp4_time(created)
        out["modified_at"] = _mp4_time(modified)

    # first video track: dimensions from tkhd, codec from stsd
    moov = _find_box(data, [b"moov"])
    if moov:
        for btype, bs, be in _iter_boxes(data, moov[0], moov[1]):
            if btype != b"trak":
                continue
            tkhd = _find_box(data, [b"tkhd"], bs, be)
            if tkhd:
                b = data[tkhd[0]:tkhd[1]]
                if len(b) >= 8:  # width/height are the trailing 16.16 fixed-point fields
                    w = int.from_bytes(b[-8:-6], "big")
                    h = int.from_bytes(b[-4:-2], "big")
                    if w and h:
                        out.setdefault("width", w)
                        out.setdefault("height", h)
            stsd = _find_box(data, [b"mdia", b"minf", b"stbl", b"stsd"], bs, be)
            if stsd and stsd[1] - stsd[0] >= 16:
                fourcc = data[stsd[0] + 12:stsd[0] + 16].decode("ascii", "ignore")
                if fourcc in _CODEC_NAMES:
                    out.setdefault("codec", _CODEC_NAMES[fourcc])
                    out.setdefault("codec_fourcc", fourcc)
            if "width" in out and "codec" in out:
                break
    return out


def _video_signals(meta: dict, truncated: bool) -> tuple[list[dict], int]:
    findings: list[dict] = []
    penalty = 0
    if not meta.get("created_at"):
        findings.append({"level": "medium",
                         "text": "No original capture timestamp in the container — the file "
                                 "was re-encoded (platforms strip device metadata on upload; "
                                 "the original recording time cannot be established)"})
        penalty += 18
    else:
        created, modified = meta.get("created_at"), meta.get("modified_at")
        if created and modified and abs((modified - created).total_seconds()) > 60:
            findings.append({"level": "medium",
                             "text": f"File was modified after recording "
                                     f"(recorded {created:%Y-%m-%d %H:%M} UTC, "
                                     f"last saved {modified:%Y-%m-%d %H:%M} UTC)"})
            penalty += 22
    if truncated:
        findings.append({"level": "info",
                         "text": "Large file — analysis covers the downloaded portion "
                                 "(container metadata is complete; full-file hash unavailable)"})
    if not findings:
        findings.append({"level": "ok",
                         "text": "Container metadata is internally consistent"})
    return findings, max(0, 100 - penalty)


def analyze_video(data: bytes, filename: str = "", truncated: bool = False) -> dict:
    """Analyze raw video bytes (MP4/MOV family). Returns a JSON-safe report
    shaped like the image report so the UI renders both uniformly."""
    base = {
        "filename": filename or "upload",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest() + ("…(partial)" if truncated else ""),
        "media_type": "video",
    }
    is_mp4 = len(data) > 12 and data[4:8] == b"ftyp"
    if not is_mp4:
        container = ("WebM/Matroska" if data[:4] == b"\x1aE\xdf\xa3"
                     else "AVI" if data[:4] == b"RIFF"
                     else "unknown")
        return {**base, "format": container,
                "perceptual_hash": None, "average_hash": None, "exif": {}, "gps": None,
                "manipulation": {"integrity_score": None, "findings": [
                    {"level": "info",
                     "text": f"{container} container — deep parsing supports the MP4/MOV "
                             "family; file hash and size are still recorded for matching."}]}}

    meta = _parse_mp4(data)
    findings, integrity = _video_signals(meta, truncated)
    dur = meta.get("duration_s")
    bitrate = round(len(data) * 8 / dur / 1000) if dur else None
    return {
        **base,
        "format": f"MP4 ({meta.get('brand', '?')})",
        "codec": meta.get("codec") or meta.get("codec_fourcc"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "duration_s": dur,
        "bitrate_kbps": bitrate if not truncated else None,
        "captured_at": meta["created_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if meta.get("created_at") else None,
        "modified_at": meta["modified_at"].strftime("%Y-%m-%d %H:%M:%S UTC") if meta.get("modified_at") else None,
        "perceptual_hash": None, "average_hash": None,
        "exif": {}, "gps": None,
        "manipulation": {"integrity_score": integrity, "findings": findings},
    }


_VIDEO_MAGIC = (b"\x1aE\xdf\xa3",)  # EBML (webm/mkv)


def _looks_like_video(data: bytes, name_l: str) -> bool:
    if any(name_l.endswith(ext) for ext in _VIDEO_EXT):
        return True
    if len(data) > 12 and data[4:8] == b"ftyp":
        return True
    return any(data.startswith(m) for m in _VIDEO_MAGIC)


def analyze_image(data: bytes, filename: str = "") -> dict:
    """Analyze raw media bytes — dispatches to the video analyzer for video
    files (by extension or magic bytes). Returns a JSON-safe forensic report."""
    sha = hashlib.sha256(data).hexdigest()
    name_l = (filename or "").lower()
    base = {
        "filename": filename or "upload",
        "size_bytes": len(data),
        "sha256": sha,
    }

    if _looks_like_video(data, name_l):
        return analyze_video(data, filename)

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
    }
