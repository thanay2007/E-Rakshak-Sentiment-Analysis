# -*- coding: utf-8 -*-
"""Face detection + embedding — the front half of the identification pipeline.

`image_analysis` used to call `face_recognition.face_locations()` on the raw
uploaded bytes and return a count. That misses faces constantly in exactly the
material this system handles (crowd photos from a protest, forwarded WhatsApp
screenshots, phone photos held sideways), and it produced nothing that could be
matched against a suspect database. This module fixes both halves:

  detection
    • EXIF orientation is applied first — a portrait phone photo stores its
      pixels landscape, and dlib's upright-face detector finds nothing in a
      sideways image. This alone was silently losing most phone uploads.
    • large images are downscaled before detection (HOG cost is quadratic in
      pixels) and the boxes are mapped back to original coordinates, so a 12 MP
      photo costs about the same as a 1 MP one
    • adaptive escalation: if a pass finds nothing we retry upsampled (small /
      distant faces in crowd shots), then optionally with the CNN detector
    • overlapping detections from different passes are merged by IoU

  quality gating (why a face may be found but not identified)
    • face size in real pixels, sharpness (variance of Laplacian), exposure and
      head pose from the 68-point landmarks
    each face gets a 0-100 quality score and a `usable_for_matching` flag, so a
    12-pixel blurred profile in the background never produces a confident
    "criminal identified" claim.

  embedding
    • 128-d encodings are computed on the ORIGINAL-resolution pixels using the
      scaled-back boxes (the encoder works on face chips, so this is cheap) and
      are what `face_db` matches against enrolled reference photos.

Everything degrades gracefully: with `face_recognition` absent or its model
weights missing, every entry point returns an "unavailable" report instead of
raising — the house style of this package.

NOTE: Face detection uses dlib via face_recognition, which is CPU-only. For GPU
acceleration, consider using insightface or PyTorch-based face detection models
as an alternative backend. The embedding comparisons in face_db (numpy operations)
are already optimized for CPU and scale well to multiple cores.
"""
from __future__ import annotations

import logging
import math

log = logging.getLogger(__name__)

# Detection runs on an image downscaled to this longest edge. 1200px keeps a
# ~50px face (the smallest we would ever trust) well above the 40px minimum
# dlib's HOG detector can resolve, while capping the cost of huge uploads.
_DETECT_MAX_DIM = 1200
_RETRY_MAX_DIM = 700          # smaller image → upsampling is affordable
_CNN_MAX_DIM = 500            # CNN is ~50x slower; only on a small image
_MAX_FACES = 40               # crowd photos: stop enriching past this many

# Quality thresholds — a face below these is reported but not matched.
_MIN_FACE_PX = 42             # below this the embedding is noise
# variance-of-Laplacian on a size-normalised crop. Originally 12.0; the social
# media evidence this tool actually sees is routinely soft-focus or
# recompressed, and that stricter gate was refusing to even attempt a search
# on faces still sharp enough for dlib to encode usefully. Lowered rather than
# removed — this only decides whether a search is attempted at all; the
# confirmed/probable/possible distance bands below are what actually guard
# against a false identification, and those are unchanged.
_MIN_SHARPNESS = 7.0
_MAX_YAW = 0.62               # nose offset / inter-eye distance ≈ 45° turn

_ENGINE: dict = {"loaded": False, "fr": None, "np": None, "cnn": False, "reason": ""}


def _load() -> dict:
    """Import face_recognition once, tolerating every way it can fail.

    When its model weights are missing the library calls quit() at import time,
    which raises SystemExit — a BaseException that slips past `except Exception`
    and would otherwise tear down the worker process.
    """
    if _ENGINE["loaded"]:
        return _ENGINE
    _ENGINE["loaded"] = True
    try:
        import numpy as np
        import face_recognition
    except BaseException as exc:  # ImportError | SystemExit | model-load errors
        _ENGINE["reason"] = f"face_recognition unavailable ({type(exc).__name__}: {exc})"
        return _ENGINE
    _ENGINE["fr"] = face_recognition
    _ENGINE["np"] = np
    try:  # the CNN detector needs the mmod weights, which ship separately
        import dlib  # noqa: F401
        _ENGINE["cnn"] = hasattr(face_recognition.api, "cnn_face_detector")
    except BaseException:
        _ENGINE["cnn"] = False
    return _ENGINE


def available() -> bool:
    return _load()["fr"] is not None


def engine_status() -> dict:
    e = _load()
    return {"available": e["fr"] is not None, "cnn_available": bool(e["cnn"]),
            "reason": e["reason"] or None}


# ── geometry helpers ───────────────────────────────────────────────────────

def _iou(a: tuple, b: tuple) -> float:
    """Intersection-over-union of two (top, right, bottom, left) boxes."""
    at, ar, ab, al = a
    bt, br, bb, bl = b
    iw = max(0, min(ar, br) - max(al, bl))
    ih = max(0, min(ab, bb) - max(at, bt))
    inter = iw * ih
    if not inter:
        return 0.0
    union = (ar - al) * (ab - at) + (br - bl) * (bb - bt) - inter
    return inter / union if union else 0.0


def _dedupe(boxes: list[tuple], threshold: float = 0.4) -> list[tuple]:
    """Keep the largest box of each overlapping group (passes at different
    upsample factors return near-duplicate boxes for the same face)."""
    kept: list[tuple] = []
    for box in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]), reverse=True):
        if all(_iou(box, k) < threshold for k in kept):
            kept.append(box)
    return kept


def _scale_box(box: tuple, factor: float, w: int, h: int) -> tuple:
    """Map a detection-space box back to original-image coordinates, clamped."""
    top, right, bottom, left = box
    return (
        max(0, min(h, int(round(top / factor)))),
        max(0, min(w, int(round(right / factor)))),
        max(0, min(h, int(round(bottom / factor)))),
        max(0, min(w, int(round(left / factor)))),
    )


# ── quality metrics ────────────────────────────────────────────────────────

def _sharpness(np, gray) -> float:
    """Variance of the Laplacian — the standard blur metric, implemented with
    array slicing so no OpenCV dependency is needed.

    The crop is first downscaled so its short edge is ~100px (never upscaled),
    which makes the number comparable between a close-up and a distant face.
    """
    h, w = gray.shape
    if h < 8 or w < 8:
        return 0.0
    step = max(1, int(min(h, w) / 100))
    g = gray[::step, ::step].astype("float32")
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
           - 4.0 * g[1:-1, 1:-1])
    return float(np.var(lap))


def _pose(landmarks: dict | None) -> dict:
    """Head pose proxies from the 68-point landmarks.

    yaw  — horizontal offset of the nose tip from the eye midpoint, normalised
           by inter-eye distance (0 = facing camera, ~0.6 ≈ 45° turned away)
    roll — tilt of the eye line in degrees
    """
    if not landmarks:
        return {"yaw": None, "roll": None}
    try:
        le = landmarks.get("left_eye") or []
        re = landmarks.get("right_eye") or []
        nose = landmarks.get("nose_tip") or landmarks.get("nose_bridge") or []
        if not (le and re and nose):
            return {"yaw": None, "roll": None}
        lx = sum(p[0] for p in le) / len(le)
        ly = sum(p[1] for p in le) / len(le)
        rx = sum(p[0] for p in re) / len(re)
        ry = sum(p[1] for p in re) / len(re)
        nx = sum(p[0] for p in nose) / len(nose)
        eye_dist = math.hypot(rx - lx, ry - ly)
        if eye_dist < 1:
            return {"yaw": None, "roll": None}
        yaw = abs(nx - (lx + rx) / 2) / eye_dist
        roll = math.degrees(math.atan2(ry - ly, rx - lx))
        return {"yaw": round(yaw, 3), "roll": round(roll, 1)}
    except Exception:
        return {"yaw": None, "roll": None}


def _quality(np, gray_crop, face_px: int, pose: dict) -> dict:
    """Score a detection 0-100 and explain, in analyst language, what limits it."""
    sharp = _sharpness(np, gray_crop)
    brightness = float(np.mean(gray_crop)) if gray_crop.size else 0.0
    issues: list[str] = []
    score = 100.0

    if face_px < _MIN_FACE_PX:
        issues.append(f"face is only {face_px}px wide — too small to identify reliably")
        score -= 45
    elif face_px < 80:
        issues.append(f"small face ({face_px}px) — identification confidence is reduced")
        score -= 18

    if sharp < _MIN_SHARPNESS:
        issues.append("image is blurred or heavily re-compressed at this face")
        score -= 35
    elif sharp < 30:
        issues.append("soft focus — moderate blur at this face")
        score -= 12

    if brightness < 45:
        issues.append("underexposed / in shadow")
        score -= 15
    elif brightness > 225:
        issues.append("overexposed — facial detail is washed out")
        score -= 15

    yaw = pose.get("yaw")
    if yaw is not None:
        if yaw > _MAX_YAW:
            issues.append("head turned away from the camera (profile view)")
            score -= 30
        elif yaw > 0.35:
            issues.append("head partly turned — embedding is less distinctive")
            score -= 12

    score = max(0, min(100, int(round(score))))
    band = "good" if score >= 70 else "fair" if score >= 40 else "poor"
    usable = (face_px >= _MIN_FACE_PX and sharp >= _MIN_SHARPNESS
              and (yaw is None or yaw <= _MAX_YAW))
    return {
        "score": score,
        "band": band,
        "face_px": face_px,
        "sharpness": round(sharp, 1),
        "brightness": round(brightness, 1),
        "yaw": pose.get("yaw"),
        "roll": pose.get("roll"),
        "issues": issues or ["clear, front-facing capture"],
        "usable_for_matching": usable,
    }


# ── detection passes ───────────────────────────────────────────────────────

def _prepare(img):
    """EXIF-orient, force RGB, and return (numpy image, width, height).

    exif_transpose is the single highest-impact fix here: phones store portrait
    shots as landscape pixels plus an orientation tag, and an upright-face
    detector finds nothing in the un-rotated buffer.
    """
    from PIL import ImageOps

    np = _load()["np"]
    try:
        img = ImageOps.exif_transpose(img) or img
    except Exception:
        pass
    rgb = img.convert("RGB")
    # dlib requires a contiguous uint8 buffer
    return np.ascontiguousarray(np.array(rgb, dtype="uint8")), rgb.width, rgb.height, rgb


def _resized(np, rgb, max_dim: int):
    """Downscale (never upscale) to `max_dim` on the longest edge.
    Returns (numpy image, scale factor applied)."""
    from PIL import Image

    longest = max(rgb.width, rgb.height)
    if longest <= max_dim:
        return np.ascontiguousarray(np.array(rgb, dtype="uint8")), 1.0
    factor = max_dim / longest
    small = rgb.resize((max(1, int(rgb.width * factor)),
                        max(1, int(rgb.height * factor))), Image.BILINEAR)
    return np.ascontiguousarray(np.array(small, dtype="uint8")), factor


def detect_faces(img, *, want_encodings: bool = True, deep: bool = False) -> dict:
    """Locate every face in a PIL image and describe each one.

    `deep=True` allows the CNN detector pass, which is far more accurate on
    turned / partially occluded faces but ~50x slower — it is opt-in per request
    rather than a default, so bulk feed analysis stays responsive.

    Returns a JSON-safe report; `faces[i]["encoding"]` is the 128-d embedding
    (or None when the face is too poor to embed) that `face_db` matches on.
    """
    e = _load()
    fr, np = e["fr"], e["np"]
    if fr is None:
        return {"available": False, "engine": None, "reason": e["reason"],
                "count": 0, "faces": [], "passes": []}

    try:
        full_np, width, height, rgb = _prepare(img)
    except Exception as exc:
        log.warning("face prepare failed: %s", exc)
        return {"available": True, "engine": None, "reason": f"decode failed: {exc}",
                "count": 0, "faces": [], "passes": []}

    passes: list[dict] = []
    boxes: list[tuple] = []

    def run(max_dim: int, upsample: int, model: str, label: str) -> list[tuple]:
        small, factor = _resized(np, rgb, max_dim)
        try:
            found = fr.face_locations(small, number_of_times_to_upsample=upsample,
                                      model=model)
        except Exception as exc:
            log.warning("face_locations(%s) failed: %s", label, exc)
            passes.append({"pass": label, "found": 0, "error": str(exc)})
            return []
        passes.append({"pass": label, "found": len(found),
                       "scale": round(factor, 3)})
        return [_scale_box(b, factor, width, height) for b in found]

    # pass 1 — the workhorse: HOG on a downscaled copy, one upsample so faces
    # roughly 40px and up in the original are resolved.
    boxes += run(_DETECT_MAX_DIM, 1, "hog", "hog-x1")

    # pass 2 — nothing found: re-run smaller but upsampled twice. Catches the
    # distant faces in crowd/protest photos that a single pass walks past.
    if not boxes:
        boxes += run(_RETRY_MAX_DIM, 2, "hog", "hog-x2")

    # pass 3 — still nothing and the caller asked for depth: CNN detector,
    # which handles turned heads, partial occlusion and odd lighting.
    if not boxes and deep and e["cnn"]:
        boxes += run(_CNN_MAX_DIM, 1, "cnn", "cnn")

    boxes = _dedupe(boxes)
    truncated = len(boxes) > _MAX_FACES
    boxes = sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[1] - b[3]),
                   reverse=True)[:_MAX_FACES]

    if not boxes:
        return {"available": True, "engine": "dlib", "count": 0, "faces": [],
                "passes": passes, "width": width, "height": height,
                "note": "No faces detected. Tried HOG at two scales"
                        + (" and the CNN detector." if deep and e["cnn"] else "."),}

    # Landmarks + encodings are computed on the ORIGINAL-resolution pixels: the
    # encoder only sees the face chip, so accuracy improves at negligible cost.
    landmarks: list[dict] = []
    try:
        landmarks = fr.face_landmarks(full_np, boxes)
    except Exception as exc:
        log.warning("face_landmarks failed: %s", exc)

    gray = None
    try:
        gray = np.dot(full_np[..., :3], [0.299, 0.587, 0.114])
    except Exception:
        pass

    faces: list[dict] = []
    for i, (top, right, bottom, left) in enumerate(boxes):
        face_px = min(right - left, bottom - top)
        crop = (gray[top:bottom, left:right] if gray is not None
                else np.zeros((1, 1)))
        pose = _pose(landmarks[i] if i < len(landmarks) else None)
        quality = _quality(np, crop, face_px, pose)
        faces.append({
            "index": i,
            "bounding_box": {"top": top, "right": right,
                             "bottom": bottom, "left": left},
            "area_ratio": round((right - left) * (bottom - top) / max(1, width * height), 4),
            "quality": quality,
            "landmarks_found": i < len(landmarks),
            "encoding": None,
        })

    if want_encodings:
        # Only embed faces worth matching — the encoder is the expensive step
        # and a 12px blur produces an embedding that matches everything.
        wanted = [f for f in faces if f["quality"]["usable_for_matching"]]
        if wanted:
            locs = [(f["bounding_box"]["top"], f["bounding_box"]["right"],
                     f["bounding_box"]["bottom"], f["bounding_box"]["left"])
                    for f in wanted]
            try:
                # model="large" (68-point alignment) must match what
                # encode_reference uses — mixing the 5- and 68-point predictors
                # aligns the chips differently and inflates match distances.
                # num_jitters=3 (was 1): a few resampled encodings averaged
                # together ride out compression noise and mild blur better than
                # a single pass, for a small, per-request cost worth paying
                # since only faces that already passed the quality gate embed.
                encs = fr.face_encodings(full_np, known_face_locations=locs,
                                         num_jitters=3, model="large")
                for f, enc in zip(wanted, encs):
                    f["encoding"] = [round(float(x), 6) for x in enc]
            except Exception as exc:
                log.warning("face_encodings failed: %s", exc)

    return {
        "available": True,
        "engine": "dlib-cnn" if any(p["pass"] == "cnn" and p["found"] for p in passes) else "dlib-hog",
        "count": len(faces),
        "truncated": truncated,
        "width": width,
        "height": height,
        "faces": faces,
        "passes": passes,
    }


def encode_reference(img, *, deep: bool = True) -> dict:
    """Embed the single best face in a reference/enrolment photo.

    Uses `num_jitters=10` and the full 68-point model: enrolment happens once
    per suspect, so the extra ~10x cost buys a materially more stable template
    than the fast path used for incoming evidence.
    """
    e = _load()
    fr, np = e["fr"], e["np"]
    if fr is None:
        return {"ok": False, "error": e["reason"] or "face_recognition unavailable"}

    report = detect_faces(img, want_encodings=False, deep=deep)
    if not report.get("faces"):
        return {"ok": False, "error": "No face found in the reference photo.",
                "detection": report}

    # Enrol the largest face; a reference photo with several people is ambiguous.
    face = max(report["faces"], key=lambda f: f["area_ratio"])
    others = len(report["faces"]) - 1
    if not face["quality"]["usable_for_matching"]:
        return {"ok": False,
                "error": "Face quality too low to enrol: "
                         + "; ".join(face["quality"]["issues"]),
                "detection": report}

    try:
        full_np, _w, _h, _rgb = _prepare(img)
        b = face["bounding_box"]
        encs = fr.face_encodings(
            full_np,
            known_face_locations=[(b["top"], b["right"], b["bottom"], b["left"])],
            num_jitters=10, model="large")
    except Exception as exc:
        return {"ok": False, "error": f"Could not encode the reference face: {exc}"}
    if not encs:
        return {"ok": False, "error": "Encoder returned no embedding for that face."}

    return {
        "ok": True,
        "encoding": [round(float(x), 6) for x in encs[0]],
        "quality": face["quality"],
        "bounding_box": face["bounding_box"],
        "other_faces_ignored": others,
    }
