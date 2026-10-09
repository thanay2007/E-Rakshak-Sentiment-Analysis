# -*- coding: utf-8 -*-
"""ArcFace embeddings — the identity half of the recogniser.

dlib (`face_detect`) is good at *finding* faces and grading them, and its
128-d embedding is what the registry was built on. It is not good at the
question this console actually asks — "is this a different photo of someone
we enrolled?" — on the people it actually sees. dlib's model was trained on a
mostly Western face set; on South Asian faces two strangers routinely land
inside its 0.6 threshold, and two photos of one person taken a year apart
routinely land outside it.

InsightFace's ArcFace (`w600k_r50`, trained on WebFace600K) is a different
class of model: 512-d, angular-margin trained, and its genuine/impostor
similarity distributions barely overlap. It runs through onnxruntime, which is
already installed for the voice stack, so this adds weights and no new native
dependency.

Alignment reuses dlib's 68-point landmarks: the five points ArcFace was
trained on (eye centres, nose tip, mouth corners) are read off them and the
face is warped onto the canonical 112×112 template with a similarity transform.
That keeps one detector in the pipeline instead of two that disagree about
where a face is.

Everything degrades: no onnxruntime, no weights, no network — `available()` is
False, embeddings come back None, and matching falls back to dlib distances.
The weights are fetched in a background thread on first use, so a fresh
install is never blocked on a 170 MB download inside a request.
"""
from __future__ import annotations

import logging
import threading

from app.config import settings

log = logging.getLogger(__name__)

DIM = 512

#: Cosine-similarity operating points for w600k_r50, measured on the 1,000 LFW
#: test pairs run through this pipeline (dlib detection + landmark alignment):
#: different people — median 0.00, 99th percentile 0.145, max 0.205; same
#: person in a different photo — 5th percentile 0.53, median 0.70. At these
#: bands 99.2% of same-person pairs were identified (98.8% "confirmed") with
#: no false identification, against dlib's 92.4% (71.8% confirmed) at its
#: own bands. LFW is cleaner than social-media evidence, so the bands stay
#: well above the impostor maximum rather than at it.
CONFIRMED_MIN = 0.40
PROBABLE_MIN = 0.32
POSSIBLE_MIN = 0.25

# The canonical ArcFace 5-point template on a 112×112 crop, in the order
# image-left eye, image-right eye, nose tip, image-left mouth corner,
# image-right mouth corner.
_TEMPLATE = (
    (38.2946, 51.6963),
    (73.5318, 51.5014),
    (56.0252, 71.7366),
    (41.5493, 92.3655),
    (70.7299, 92.2041),
)
_SIZE = 112

_lock = threading.Lock()
_state: dict = {"session": None, "input": None, "tried": False,
                "downloading": False, "reason": ""}


# ── model ──────────────────────────────────────────────────────────────────

def _model_path(*, allow_download: bool) -> str | None:
    if settings.FACE_ARCFACE_MODEL:
        return settings.FACE_ARCFACE_MODEL
    from huggingface_hub import hf_hub_download

    try:
        return hf_hub_download(settings.FACE_ARCFACE_REPO, settings.FACE_ARCFACE_FILE,
                               local_files_only=True)
    except Exception:
        if not allow_download:
            return None
    return hf_hub_download(settings.FACE_ARCFACE_REPO, settings.FACE_ARCFACE_FILE)


def _open(path: str) -> None:
    import onnxruntime as ort

    providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                 if p in ort.get_available_providers()]
    sess = ort.InferenceSession(path, providers=providers)
    _state["session"] = sess
    _state["input"] = sess.get_inputs()[0].name
    _state["reason"] = ""
    log.info("ArcFace recogniser loaded (%s)", providers[0])


def _download() -> None:
    try:
        path = _model_path(allow_download=True)
        with _lock:
            _open(path)
    except BaseException as exc:
        _state["reason"] = f"ArcFace weights unavailable ({type(exc).__name__}: {exc})"
        log.warning("%s — face matching stays on dlib", _state["reason"])
    finally:
        _state["downloading"] = False


def _load():
    """The ONNX session, or None. Never blocks on the network."""
    if _state["session"] is not None or not settings.FACE_ARCFACE:
        return _state["session"]
    with _lock:
        if _state["session"] is not None or _state["tried"]:
            return _state["session"]
        _state["tried"] = True
        try:
            path = _model_path(allow_download=False)
            if path:
                _open(path)
                return _state["session"]
        except BaseException as exc:  # ImportError, corrupt file, bad provider
            _state["reason"] = f"ArcFace unavailable ({type(exc).__name__}: {exc})"
            log.warning("%s — face matching stays on dlib", _state["reason"])
            return None
        _state["downloading"] = True
        _state["reason"] = "ArcFace weights are downloading"
        threading.Thread(target=_download, name="arcface-download", daemon=True).start()
        return None


def available() -> bool:
    return _load() is not None


def status() -> dict:
    _load()
    return {"arcface": _state["session"] is not None,
            "arcface_downloading": _state["downloading"],
            "arcface_reason": _state["reason"] or None}


# ── alignment ──────────────────────────────────────────────────────────────

def five_points(landmarks: dict | None):
    """ArcFace's five alignment points, read off dlib's 68-point landmarks.

    face_recognition names its groups from the viewer's side, which is the
    order the template uses: `left_eye` is points 36-41 (image-left),
    `nose_bridge[-1]` is point 30 (the tip), `top_lip[0]`/`[6]` are 48/54
    (the mouth corners).
    """
    import numpy as np

    try:
        le = np.mean(np.asarray(landmarks["left_eye"], dtype="float64"), axis=0)
        re = np.mean(np.asarray(landmarks["right_eye"], dtype="float64"), axis=0)
        nose = np.asarray(landmarks["nose_bridge"][-1], dtype="float64")
        lip = landmarks["top_lip"]
        ml = np.asarray(lip[0], dtype="float64")
        mr = np.asarray(lip[6], dtype="float64")
    except (KeyError, IndexError, TypeError):
        return None
    return np.stack([le, re, nose, ml, mr])


def _similarity(src, dst):
    """Least-squares similarity transform src→dst (Umeyama), as a 2×3 matrix."""
    import numpy as np

    n = src.shape[0]
    mu_s, mu_d = src.mean(0), dst.mean(0)
    sc, dc = src - mu_s, dst - mu_d
    cov = dc.T @ sc / n
    u, s, vt = np.linalg.svd(cov)
    d = np.ones(2)
    if np.linalg.det(cov) < 0:
        d[-1] = -1
    r = u @ np.diag(d) @ vt
    var_s = (sc ** 2).sum() / n
    scale = (s * d).sum() / var_s if var_s else 1.0
    m = np.zeros((2, 3))
    m[:, :2] = scale * r
    m[:, 2] = mu_d - scale * r @ mu_s
    return m


def align(rgb_np, points):
    """Warp a face onto the 112×112 ArcFace template. Returns an HxWx3 uint8."""
    import numpy as np
    from PIL import Image

    m = _similarity(points, np.asarray(_TEMPLATE, dtype="float64"))
    a_inv = np.linalg.inv(m[:, :2])
    t_inv = -a_inv @ m[:, 2]
    # PIL samples at pixel centres (+0.5) while landmarks index pixels from 0,
    # so the inverse map is shifted by half a pixel on both sides.
    half = np.array([0.5, 0.5])
    t_inv = t_inv + half - a_inv @ half
    coeffs = (a_inv[0, 0], a_inv[0, 1], t_inv[0], a_inv[1, 0], a_inv[1, 1], t_inv[1])
    img = Image.fromarray(rgb_np)
    chip = img.transform((_SIZE, _SIZE), Image.AFFINE, coeffs, resample=Image.BILINEAR)
    return np.asarray(chip, dtype="uint8")


# ── embedding ──────────────────────────────────────────────────────────────

def embed_chips(chips: list) -> list[list[float]]:
    """Embed aligned 112×112 RGB chips. Each chip is embedded together with its
    mirror image and the two summed — a free, standard gain in stability on
    turned heads and uneven lighting."""
    import numpy as np

    sess = _load()
    if sess is None or not chips:
        return []
    batch = []
    for chip in chips:
        x = (chip.astype("float32") - 127.5) / 127.5
        batch.append(x)
        batch.append(x[:, ::-1, :])
    # One image per run: the exported graph declares a batch of 1 on its output,
    # and onnxruntime logs a shape warning on every batched call otherwise.
    out = np.concatenate([
        sess.run(None, {_state["input"]: np.ascontiguousarray(x.transpose(2, 0, 1)[None])})[0]
        for x in batch])
    out = out.reshape(len(chips), 2, -1).sum(axis=1)
    out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-12
    return [[round(float(v), 6) for v in row] for row in out]


def embed_faces(rgb_np, landmarks_list: list) -> list[list[float] | None]:
    """One ArcFace embedding per landmark set (None where alignment failed)."""
    if _load() is None:
        return [None] * len(landmarks_list)
    chips, slots = [], []
    for i, lm in enumerate(landmarks_list):
        pts = five_points(lm)
        if pts is None:
            continue
        try:
            chips.append(align(rgb_np, pts))
            slots.append(i)
        except Exception as exc:
            log.warning("ArcFace alignment failed: %s", exc)
    out: list = [None] * len(landmarks_list)
    try:
        for i, vec in zip(slots, embed_chips(chips)):
            out[i] = vec
    except Exception as exc:
        log.warning("ArcFace embedding failed: %s", exc)
    return out


def embed_largest_face(img) -> list[float] | None:
    """Embed the largest face in a PIL image — used to backfill references
    that were enrolled before this model existed, from their stored photo."""
    if _load() is None:
        return None
    from app.osint.face_detect import detect_faces

    report = detect_faces(img, want_encodings=True)
    faces = [f for f in report.get("faces") or [] if f.get("arcface")]
    if not faces:
        return None
    return max(faces, key=lambda f: f["area_ratio"])["arcface"]


# ── scoring ────────────────────────────────────────────────────────────────

def similarity(a: list[float], b: list[float]) -> float:
    import numpy as np

    return float(np.dot(np.asarray(a, dtype="float64"), np.asarray(b, dtype="float64")))


def band_for(sim: float) -> str:
    if sim >= CONFIRMED_MIN:
        return "confirmed"
    if sim >= PROBABLE_MIN:
        return "probable"
    if sim >= POSSIBLE_MIN:
        return "possible"
    return "no_match"


def confidence_for(sim: float) -> float:
    """0 at a stranger's typical similarity (0.15), 1 at an easy same-person
    pair (0.60) — linear in between, so it tracks the metric."""
    return round(max(0.0, min(1.0, (sim - 0.15) / 0.45)), 3)
