"""The reference gallery: naming, thresholds, and the line it must not cross.

The gallery exists so an officer can teach the console a face by dropping a
photo into a folder. Two things about that have to hold:

  · the folder layout is the only interface, so the name derived from it has to
    be what a person would expect — and "Cristiano Ronaldo", "cristiano-ronaldo"
    and "Cristiano_Ronaldo" have to be ONE person, or the same face ends up
    enrolled three times under three names and matches at random between them
  · a gallery hit names a face; it is not a criminal record. The two searches
    are reported separately, and the thresholds a name is claimed at must be the
    registry's own, so "confirmed" means the same evidence either way.

Run:  cd backend && python -m pytest tests/test_face_gallery.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.osint import face_db, face_gallery

ROOT = Path("/gallery")


@pytest.mark.parametrize("path,expected", [
    # a folder names everyone inside it, whatever the files are called
    (ROOT / "Cristiano Ronaldo" / "IMG_20240817_0031.jpg", "Cristiano Ronaldo"),
    (ROOT / "Lionel Messi" / "OIP (1).webp", "Lionel Messi"),
    # a loose file names itself
    (ROOT / "narendra-modi.jpg", "Narendra Modi"),
    (ROOT / "amit_shah.png", "Amit Shah"),
    # lowercase folders are title-cased; deliberate casing is left alone
    (ROOT / "messi" / "a.jpg", "Messi"),
    (ROOT / "CR7" / "a.jpg", "CR7"),
    # nested deeper than one level still belongs to the top folder
    (ROOT / "Bhupendra Patel" / "rally" / "close.jpg", "Bhupendra Patel"),
])
def test_person_name_follows_the_folder(path, expected):
    assert face_gallery.person_name(path, ROOT) == expected


@pytest.mark.parametrize("a,b", [
    ("Cristiano Ronaldo", "cristiano-ronaldo"),
    ("Cristiano Ronaldo", "CristianoRonaldo"),
    ("Lionel  Messi", "lionel_messi"),
])
def test_spelling_variants_are_the_same_person(a, b):
    assert face_gallery.person_key(a) == face_gallery.person_key(b)


def test_filename_noise_does_not_become_part_of_a_name():
    """Downloads arrive called things like `wallpaper-4k`; that is not a name."""
    assert face_gallery.person_name(ROOT / "ronaldo-wallpaper-hd.jpg", ROOT) == "Ronaldo"


def test_thresholds_match_the_suspect_registry():
    """A "confirmed" match must mean the same strength of evidence in both
    halves of identification, or the word means nothing on screen."""
    assert face_gallery.CONFIRMED_MAX == face_db.CONFIRMED_MAX
    assert face_gallery.PROBABLE_MAX == face_db.PROBABLE_MAX
    assert face_gallery.POSSIBLE_MAX == face_db.POSSIBLE_MAX


@pytest.mark.parametrize("distance,band", [
    (0.08, "confirmed"),    # measured: a second photo of the same person
    (0.44, "confirmed"),
    (0.50, "probable"),
    (0.55, "possible"),
    (0.65, "no_match"),     # measured: the closest Ronaldo/Messi pair was 0.65
])
def test_bands(distance, band):
    assert face_gallery.band_for(distance) == band


def test_a_probe_with_no_embedding_is_never_a_match():
    result = face_gallery.match(None, [])          # session is never touched
    assert result["identified"] is False
    assert result["searched"] is False


def test_confidence_never_leaves_zero_to_one():
    for d in (0.0, 0.25, 0.5, 0.75, 1.2):
        assert 0.0 <= face_gallery.confidence_for(d) <= 1.0


# ── ArcFace scoring (face_db.compare) ──────────────────────────────────────

def _unit(v):
    import math
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _arc(seed: int, near: list[float] | None = None, mix: float = 0.0):
    import random
    rng = random.Random(seed)
    v = [rng.gauss(0, 1) for _ in range(512)]
    if near is not None:
        v = [mix * a + (1 - mix) * b for a, b in zip(near, _unit(v))]
    return _unit(v)


def test_arcface_decides_when_both_sides_have_it():
    """dlib distance says stranger, ArcFace says same person: ArcFace wins,
    because it is the model that is actually right about that case."""
    a = _arc(1)
    same = _arc(2, near=a, mix=0.8)
    c = face_db.compare([0.0] * 128, a, [0.1] * 128, same)
    assert c["metric"] == "arcface"
    assert c["band"] == "confirmed"


def test_falls_back_to_dlib_without_arcface_on_one_side():
    c = face_db.compare([0.0] * 128, _arc(1), [0.02] * 128, None)
    assert c["metric"] == "dlib"
    assert c["band"] == face_db.band_for(c["distance"])


def test_no_shared_embedding_is_not_a_comparison():
    assert face_db.compare(None, _arc(1), [0.0] * 128, None) is None


def test_two_strangers_are_not_a_match_on_arcface():
    c = face_db.compare(None, _arc(1), None, _arc(99))
    assert c["band"] == "no_match"


def test_arcface_reason_names_the_metric():
    c = face_db.compare(None, _arc(1), None, _arc(1))
    assert "ArcFace" in face_db.evidence_text(c)
