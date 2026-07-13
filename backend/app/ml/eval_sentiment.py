# -*- coding: utf-8 -*-
"""Evaluate the SAVED fine-tuned sentiment model on the held-out test split
(no training) — overall and per-language accuracy / macro-F1. The test split
is rebuilt deterministically from the raw dataset files (same seed as
training), so it is identical to the split the model was evaluated on.

Usage (from backend/):  python -m app.ml.eval_sentiment
Rewrites ml/sentiment_eval_report.json.
"""
import json
from collections import defaultdict

from app.config import settings
from app.ml.corpus import load_corpus
from app.ml.train_sentiment import OUT_DIR, SENT_LABELS


def main() -> None:
    import numpy as np
    import torch
    from transformers import pipeline as hf_pipeline

    if not OUT_DIR.exists():
        raise SystemExit("No fine-tuned model — run  python -m app.ml.train_sentiment  first.")
    print("Rebuilding the held-out test split from the raw dataset files ...")
    _, rows = load_corpus(verbose=False)
    label2id = {l: i for i, l in enumerate(SENT_LABELS)}

    clf = hf_pipeline("text-classification", model=str(OUT_DIR), tokenizer=str(OUT_DIR),
                      truncation=True, device=0 if torch.cuda.is_available() else -1)
    outs = clf([r["text"] for r in rows], batch_size=64)
    preds = np.array([label2id[o["label"]] for o in outs])
    golds = np.array([label2id[r["label"]] for r in rows])

    def scores(p, g):
        acc = float((p == g).mean())
        f1s = []
        for c in range(3):
            if not ((g == c).any() or (p == c).any()):
                continue
            tp = int(((p == c) & (g == c)).sum())
            fp = int(((p == c) & (g != c)).sum())
            fn = int(((p != c) & (g == c)).sum())
            pr = tp / (tp + fp) if tp + fp else 0.0
            rc = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
        return round(acc, 4), round(float(np.mean(f1s)), 4)

    by_lang: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_lang[r["lang"]].append(i)
    per_lang = {}
    print(f"{'language':<10}{'n':>6}{'acc':>8}{'macroF1':>9}")
    print("-" * 33)
    for lang, idxs in sorted(by_lang.items()):
        acc, f1 = scores(preds[idxs], golds[idxs])
        per_lang[lang] = {"n": len(idxs), "accuracy": acc, "macro_f1": f1}
        print(f"{lang:<10}{len(idxs):>6}{acc:>8.3f}{f1:>9.3f}")
    acc, f1 = scores(preds, golds)
    print(f"\noverall acc={acc:.3f}  macro_f1={f1:.3f}")

    report = {"model": str(OUT_DIR), "test_size": len(rows),
              "overall": {"accuracy": acc, "macro_f1": f1}, "per_language": per_lang}
    out = settings.MODELS_DIR.parent / "sentiment_eval_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report -> {out}")


if __name__ == "__main__":
    main()
