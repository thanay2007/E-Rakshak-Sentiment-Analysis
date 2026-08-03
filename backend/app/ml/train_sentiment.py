# -*- coding: utf-8 -*-
"""Fine-tune MuRIL on the REAL multilingual sentiment datasets downloaded by
app.ml.download_datasets. The corpus (English / Hindi / Gujarati / Hinglish /
Gujlish, labels: negative / neutral / positive) is built IN MEMORY by
app.ml.corpus, straight from the raw CSV/parquet/CoNLL files under
app/data/datasets/ — no intermediate JSON is ever written.

google/muril-base-cased is Google's fully-trained Indic transformer,
pretrained on 17 Indian languages INCLUDING transliterated (romanized) text —
exactly the Hinglish/Gujlish case. The saved model is auto-detected by
transformer_engine (NLP_MODE=full) and replaces the generic
cardiffnlp/twitter-xlm-roberta-base-sentiment.

Usage (from backend/):
    python -m app.ml.download_datasets     # once, fetches the raw datasets
    python -m app.ml.train_sentiment                    # 3 epochs
    python -m app.ml.train_sentiment --epochs 2 --batch 32
Writes ml/models/sentiment-classifier/ + ml/sentiment_eval_report.json
(overall and PER-LANGUAGE accuracy / macro-F1 on the held-out test set).
"""
import argparse
import json
from collections import Counter, defaultdict

from app.config import settings
from app.ml.corpus import load_corpus, summarize

SENT_LABELS = ["negative", "neutral", "positive"]
OUT_DIR = settings.MODELS_DIR / "sentiment-classifier"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/muril-base-cased")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-len", type=int, default=128)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    import numpy as np
    import torch
    from datasets import Dataset
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              Trainer, TrainingArguments)

    from app.ml.device import get_device
    device = get_device()
    print(f"Training on device: {device}\n")
    print("Building corpus from the raw dataset files ...")
    train_rows, test_rows = load_corpus(seed=args.seed)
    summarize(train_rows, test_rows)
    label2id = {l: i for i, l in enumerate(SENT_LABELS)}
    id2label = {i: l for l, i in label2id.items()}
    print(f"\ntrain={len(train_rows)}  test={len(test_rows)}  "
          f"langs={dict(Counter(r['lang'] for r in train_rows))}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)

    def to_ds(rows):
        ds = Dataset.from_dict({"text": [r["text"] for r in rows],
                                "label": [label2id[r["label"]] for r in rows]})
        return ds.map(lambda b: tokenizer(b["text"], truncation=True,
                                          max_length=args.max_len), batched=True)

    train_ds, eval_ds = to_ds(train_rows), to_ds(test_rows)

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=3, label2id=label2id, id2label=id2label)

    # class weights — neutral is scarce in the binary-review sources
    counts = Counter(r["label"] for r in train_rows)
    total = sum(counts.values())
    weights = torch.tensor([total / (3 * counts[l]) for l in SENT_LABELS],
                           dtype=torch.float)
    print("class weights:", {l: round(float(w), 3) for l, w in zip(SENT_LABELS, weights)})

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kw):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            loss = torch.nn.functional.cross_entropy(
                outputs.logits, labels, weight=weights.to(outputs.logits.device))
            return (loss, outputs) if return_outputs else loss

    def metrics(pred):
        preds = np.argmax(pred.predictions, axis=-1)
        acc = float((preds == pred.label_ids).mean())
        f1s = []
        for c in range(3):
            tp = int(((preds == c) & (pred.label_ids == c)).sum())
            fp = int(((preds == c) & (pred.label_ids != c)).sum())
            fn = int(((preds != c) & (pred.label_ids == c)).sum())
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * p * r / (p + r) if p + r else 0.0)
        return {"accuracy": acc, "macro_f1": float(np.mean(f1s))}

    use_cuda = torch.cuda.is_available()
    trainer = WeightedTrainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(OUT_DIR / "checkpoints"),
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch,
            per_device_eval_batch_size=args.batch * 2,
            learning_rate=args.lr,
            warmup_ratio=0.06,
            eval_strategy="epoch",
            save_strategy="no",
            logging_steps=50,
            fp16=use_cuda,
            report_to=[],
        ),
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        processing_class=tokenizer,
        compute_metrics=metrics,
    )
    print(f"Training on {'CUDA' if use_cuda else 'CPU'} ...")
    trainer.train()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    print(f"Saved fine-tuned sentiment model -> {OUT_DIR}")

    # ── per-language report ─────────────────────────────────────────────────
    predictions = trainer.predict(eval_ds).predictions
    preds = np.argmax(predictions, axis=-1)
    per_lang: dict[str, dict] = {}
    by_lang: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(test_rows):
        by_lang[r["lang"]].append(i)
    for lang, idxs in sorted(by_lang.items()):
        golds = np.array([label2id[test_rows[i]["label"]] for i in idxs])
        p = preds[idxs]
        acc = float((p == golds).mean())
        f1s = []
        for c in range(3):
            if not ((golds == c).any() or (p == c).any()):
                continue
            tp = int(((p == c) & (golds == c)).sum())
            fp = int(((p == c) & (golds != c)).sum())
            fn = int(((p != c) & (golds == c)).sum())
            pr = tp / (tp + fp) if tp + fp else 0.0
            rc = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
        per_lang[lang] = {"n": len(idxs), "accuracy": round(acc, 4),
                          "macro_f1": round(float(np.mean(f1s)), 4)}

    overall = metrics(type("P", (), {"predictions": predictions,
                                     "label_ids": np.array([label2id[r["label"]] for r in test_rows])}))
    report = {"model": args.model, "epochs": args.epochs,
              "train_size": len(train_rows), "test_size": len(test_rows),
              "overall": {k: round(v, 4) for k, v in overall.items()},
              "per_language": per_lang}
    out = settings.MODELS_DIR.parent / "sentiment_eval_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'language':<10}{'n':>6}{'acc':>8}{'macroF1':>9}")
    print("-" * 33)
    for lang, m in per_lang.items():
        print(f"{lang:<10}{m['n']:>6}{m['accuracy']:>8.3f}{m['macro_f1']:>9.3f}")
    print(f"\noverall acc={overall['accuracy']:.3f}  macro_f1={overall['macro_f1']:.3f}")
    print(f"Report -> {out}\nSet NLP_MODE=full to serve the fine-tuned model.")


if __name__ == "__main__":
    main()
