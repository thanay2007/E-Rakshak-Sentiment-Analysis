# -*- coding: utf-8 -*-
"""Fine-tune an Indic-capable transformer on the 4-category threat dataset.

Default base model: google/muril-base-cased (Google MuRIL — pretrained on 17
Indian languages INCLUDING transliterated/romanized text, so it covers
Hindi, Gujarati and Hinglish natively). --model xlm-roberta-base is an
alternative. (ai4bharat/indic-bert is gated on HF now and needs a login.)
The saved model is picked up automatically by transformer_engine when
NLP_MODE=full (it outranks zero-shot).

Requires the heavy stack:  pip install -r requirements-ml.txt
Usage (from backend/):
    python -m app.ml.train                      # MuRIL, 3 epochs
    python -m app.ml.train --model xlm-roberta-base --epochs 4
"""
import argparse
import json

from app.config import THREAT_LABELS, settings
from app.ml.make_dataset import build


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="google/muril-base-cased")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    args = ap.parse_args()

    import numpy as np
    import torch  # noqa: F401 — fail fast with a clear message if missing
    from datasets import Dataset
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                              Trainer, TrainingArguments)

    train_path, test_path = build()
    label2id = {l: i for i, l in enumerate(THREAT_LABELS)}
    id2label = {i: l for l, i in label2id.items()}

    def load(path):
        rows = [json.loads(l) for l in open(path, encoding="utf-8")]
        return Dataset.from_dict({
            "text": [r["text"] for r in rows],
            "label": [label2id[r["label"]] for r in rows],
        })

    train_ds, eval_ds = load(train_path), load(test_path)
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    def tok(batch):
        return tokenizer(batch["text"], truncation=True, max_length=128)

    train_ds = train_ds.map(tok, batched=True)
    eval_ds = eval_ds.map(tok, batched=True)

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=len(THREAT_LABELS), label2id=label2id, id2label=id2label,
    )

    def metrics(pred):
        preds = np.argmax(pred.predictions, axis=-1)
        acc = (preds == pred.label_ids).mean()
        return {"accuracy": acc}

    out_dir = settings.MODELS_DIR / "threat-classifier"
    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=str(out_dir / "checkpoints"),
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch,
            learning_rate=args.lr,
            eval_strategy="epoch",
            save_strategy="no",
            logging_steps=20,
            report_to=[],
        ),
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        processing_class=tokenizer,
        compute_metrics=metrics,
    )
    trainer.train()

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    print(f"\nSaved fine-tuned model -> {out_dir}")
    print("Set NLP_MODE=full to serve it. Run python -m app.ml.evaluate for full metrics.")


if __name__ == "__main__":
    main()
