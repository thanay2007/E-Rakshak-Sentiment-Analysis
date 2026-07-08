# -*- coding: utf-8 -*-
"""Merge public hate-speech / code-mixed datasets into the SENTINEL training set.

Supported input shapes (CSV/TSV with a header):
  • HASOC (hasoc.github.io — free registration required to download):
      columns: text, task_1 (HOF/NOT) [, task_2 (HATE/OFFN/PRFN)]
  • Generic: columns: text, label  (label already one of the 4 SENTINEL labels)

Label mapping (documented for judges):
  HOF + HATE  -> Inflammatory        (hateful but not an explicit call to act)
  HOF + OFFN  -> Inflammatory
  HOF (else)  -> Inflammatory
  NOT         -> Neutral
HASOC has no fake-news / incitement split, so those two classes always come
from the SENTINEL synthetic corpus; public data widens Inflammatory/Neutral
coverage with real code-mixed text.

Usage (from backend/):
    python -m app.ml.prepare_public_data --input path/to/hasoc_hi_train.tsv
"""
import argparse
import csv
import json

from app.config import THREAT_LABELS, settings


def map_row(row: dict) -> tuple[str, str] | None:
    text = (row.get("text") or row.get("tweet") or row.get("Tweet") or "").strip()
    if not text:
        return None
    label = (row.get("label") or "").strip()
    if label in THREAT_LABELS:
        return text, label
    t1 = (row.get("task_1") or row.get("task1") or "").upper()
    if t1 == "HOF":
        return text, "Inflammatory"
    if t1 == "NOT":
        return text, "Neutral"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV/TSV file to merge")
    ap.add_argument("--out", default=str(settings.DATA_DIR / "train.jsonl"))
    args = ap.parse_args()

    delimiter = "\t" if args.input.endswith((".tsv", ".txt")) else ","
    added = 0
    with open(args.input, encoding="utf-8", newline="") as f_in, \
            open(args.out, "a", encoding="utf-8") as f_out:
        for row in csv.DictReader(f_in, delimiter=delimiter):
            mapped = map_row(row)
            if mapped:
                f_out.write(json.dumps({"text": mapped[0], "label": mapped[1],
                                        "lang": "external"}, ensure_ascii=False) + "\n")
                added += 1
    print(f"Merged {added} external samples into {args.out}")
    print("Re-run python -m app.ml.train to fine-tune with the enriched set.")


if __name__ == "__main__":
    main()
