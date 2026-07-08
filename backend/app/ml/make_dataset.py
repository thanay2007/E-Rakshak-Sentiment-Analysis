# -*- coding: utf-8 -*-
"""Build the labeled train/test datasets (JSONL: {"text", "label", "lang"}).

Sources:
  1. The SENTINEL synthetic multilingual corpus (balanced across the 4 threat
     categories and 4 languages, distinct RNG seeds for train vs test so no
     identical slot-filled sample leaks across the split).
  2. Optionally merged public data (HASOC-style) via prepare_public_data.py.

Usage:  python -m app.ml.make_dataset  (from backend/)
"""
import json

from app.config import settings
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


def build(force: bool = False) -> tuple[str, str]:
    train_path = settings.DATA_DIR / "train.jsonl"
    test_path = settings.DATA_DIR / "test.jsonl"
    if train_path.exists() and test_path.exists() and not force:
        return str(train_path), str(test_path)

    # Disjoint slot vocabularies (cities) per split so no slot-filled text can
    # appear in both; an exact-match filter stays as a safety net.
    train_cities = ["Ahmedabad", "Surat", "Vadodara", "Rajkot", "Gandhinagar"]
    test_cities = ["Bhavnagar", "Jamnagar", "Junagadh"]
    train_rows = _samples(Simulator(seed=2024, cities=train_cities), TRAIN_PER_CLASS)
    test_rows = _samples(Simulator(seed=9090, cities=test_cities), TEST_PER_CLASS)
    train_texts = {r["text"] for r in train_rows}
    test_rows = [r for r in test_rows if r["text"] not in train_texts]  # hard de-leak

    for path, rows in [(train_path, train_rows), (test_path, test_rows)]:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {len(train_rows)} train -> {train_path}")
    print(f"Wrote {len(test_rows)} test  -> {test_path}")
    return str(train_path), str(test_path)


if __name__ == "__main__":
    build(force=True)
