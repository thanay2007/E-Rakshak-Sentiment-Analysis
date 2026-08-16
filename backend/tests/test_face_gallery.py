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
