# -*- coding: utf-8 -*-
"""Build the labeled threat train/test datasets IN MEMORY (rows of
{"text", "label", "lang"}) — nothing is written to disk.

Source: the SENTINEL synthetic multilingual corpus (balanced across the 4
threat categories and 4 languages, distinct RNG seeds AND disjoint slot
vocabularies for train vs test so no slot-filled sample leaks across the
split). No real public hate-speech dataset covers these exact 4 operational
categories, which is why this corpus stays synthetic — the sentiment model,
by contrast, trains purely on real public datasets (see app.ml.corpus).

Usage:  python -m app.ml.make_dataset   (from backend/, prints stats)
"""
from app.data.simulator import Simulator
from app.data.templates import TEMPLATES

TRAIN_PER_CLASS = 400
TEST_PER_CLASS = 60


def _samples(sim: Simulator, per_class: int) -> list[dict]:
    from datetime import datetime, timezone

    from app.ml.language import detect_language

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows, seen = [], set()
    for category in TEMPLATES:
        made, attempts = 0, 0
        while made < per_class and attempts < per_class * 30:
            attempts += 1
            raw = sim.make_post(now, category=category)
            if raw.text in seen:
                continue
            seen.add(raw.text)
            lang, _ = detect_language(raw.text)
            rows.append({"text": raw.text, "label": category, "lang": lang})
            made += 1
    return rows


def build() -> tuple[list[dict], list[dict]]:
    """Return (train_rows, test_rows) — deterministic, nothing written."""
    # Disjoint slot vocabularies (cities) per split so no slot-filled text can
    # appear in both; an exact-match filter stays as a safety net.
    train_cities = ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar"]
    test_cities = ["Bhavnagar", "Jamnagar", "Junagadh"]
    train_rows = _samples(Simulator(seed=2024, cities=train_cities), TRAIN_PER_CLASS)
    test_rows = _samples(Simulator(seed=9090, cities=test_cities), TEST_PER_CLASS)
    train_texts = {r["text"] for r in train_rows}
    test_rows = [r for r in test_rows if r["text"] not in train_texts]  # hard de-leak
    return train_rows, test_rows


if __name__ == "__main__":
    train_rows, test_rows = build()
    print(f"Built {len(train_rows)} train / {len(test_rows)} test rows (in memory)")
