# -*- coding: utf-8 -*-
"""Evaluate the ACTIVE NLP pipeline (lite or full — whatever NLP_MODE selects)
on the held-out test set. Reports accuracy + per-category precision/recall/F1
and a confusion matrix; writes ml/eval_report.json for the record.

Usage:  python -m app.ml.evaluate  (from backend/)

Honest caveat (also in the README): the built-in test set is generated from
the same template families as training data, so treat these numbers as a
pipeline sanity benchmark; mix in public HASOC-style data via
prepare_public_data.py for an external measure.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from app.config import THREAT_LABELS, settings
from app.ml.make_dataset import build
from app.ml.pipeline import get_pipeline
from app.schemas import RawPost


def evaluate() -> dict:
    _, test_path = build()
    rows = [json.loads(l) for l in open(test_path, encoding="utf-8")]
    pipeline = get_pipeline()
    print(f"Evaluating {len(rows)} held-out samples with NLP_MODE={pipeline.mode} ...")

    preds = []
    for i in range(0, len(rows), 64):
        chunk = rows[i:i + 64]
        raws = [RawPost(platform="X", author_handle="eval", text=r["text"]) for r in chunk]
        preds.extend(e["threat_label"] for e in pipeline.enrich_batch(raws))

    golds = [r["label"] for r in rows]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for g, p in zip(golds, preds):
        confusion[g][p] += 1

    per_class = {}
    for label in THREAT_LABELS:
        tp = confusion[label][label]
        fn = sum(confusion[label].values()) - tp
        fp = sum(confusion[g][label] for g in THREAT_LABELS if g != label)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per_class[label] = {"precision": round(prec, 3), "recall": round(rec, 3),
                            "f1": round(f1, 3), "support": tp + fn}

    accuracy = sum(1 for g, p in zip(golds, preds) if g == p) / len(golds)
    macro_f1 = sum(m["f1"] for m in per_class.values()) / len(per_class)

    report = {
        "nlp_mode": pipeline.mode,
        "samples": len(rows),
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion_matrix": {g: dict(confusion[g]) for g in THREAT_LABELS},
    }

    print(f"\n{'Category':<26}{'Prec':>7}{'Rec':>7}{'F1':>7}{'N':>6}")
    print("-" * 53)
    for label, m in per_class.items():
        print(f"{label:<26}{m['precision']:>7.3f}{m['recall']:>7.3f}{m['f1']:>7.3f}{m['support']:>6}")
    print("-" * 53)
    print(f"{'Accuracy':<26}{accuracy:>7.3%}   Macro-F1 {macro_f1:.3f}")

    out = Path(__file__).parent / "eval_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved -> {out}")
    return report


if __name__ == "__main__":
    evaluate()
