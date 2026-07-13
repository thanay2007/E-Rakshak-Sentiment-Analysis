# -*- coding: utf-8 -*-
"""ONE command that rebuilds everything .gitignore keeps out of the repo and
trains both models from scratch. After a fresh  git clone  (with a venv
active), run from backend/:

    python -m app.ml.bootstrap

and it will, in order:
  1. install the base + ML dependencies (torch is pulled from the CUDA wheel
     index when possible, falling back to the CPU build),
  2. download every raw public dataset from kaggle.com, huggingface.co and
     github.com into app/data/datasets/ (original CSV/parquet/CoNLL files,
     ~400 MB) — no API keys needed,
  2b. [only with GROQ_API_KEY in backend/.env] LLM-augment all 5 language
     forms -> app/data/datasets/groq-augmented/ (~14k rows; 2-3 h on the free
     tier, resumable; --skip-groq to opt out),
  3. fine-tune the MuRIL threat classifier  -> app/ml/models/threat-classifier/
  4. fine-tune the MuRIL sentiment model on the raw datasets
                                            -> app/ml/models/sentiment-classifier/
     (+ per-language eval report app/ml/sentiment_eval_report.json)
  5. train the TF-IDF + LinearSVC baseline for comparison
                                            -> app/ml/baseline_report.json
  6. evaluate the threat pipeline           -> app/ml/eval_report.json

Flags:
    --no-install     skip the pip installs (deps already present)
    --skip-groq      skip the LLM augmentation (saves 2-3 h)
    --skip-threat    only rebuild datasets + the sentiment model
    --epochs N       sentiment fine-tune epochs (default 3)

Everything is idempotent: already-downloaded datasets are kept, models are
retrained. On a GPU (fp16 auto) the whole run is roughly an hour; CPU works
too, just slower.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

STEP_TIMEOUT = None   # let training run as long as it needs


def run(title: str, args: list[str], env_utf8: bool = True) -> None:
    import os

    print(f"\n{'=' * 70}\n  {title}\n  $ {' '.join(args)}\n{'=' * 70}", flush=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    result = subprocess.run(args, env=env)
    if result.returncode != 0:
        raise SystemExit(f"step failed ({title}) — fix the error above and re-run "
                         f"python -m app.ml.bootstrap (finished steps are kept).")
    print(f"  done in {time.time() - t0:,.0f}s", flush=True)


def ensure_torch() -> None:
    """Install torch from the CUDA wheel index when absent (plain PyPI ships
    the CPU-only build on Windows); fall back to the CPU wheel if that fails."""
    try:
        import torch  # noqa: F401
        return
    except ImportError:
        pass
    py = sys.executable
    cuda_index = "https://download.pytorch.org/whl/cu128"
    if subprocess.run([py, "-m", "pip", "install", "torch",
                       "--index-url", cuda_index]).returncode != 0:
        run("torch (CPU fallback)", [py, "-m", "pip", "install", "torch"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--skip-threat", action="store_true")
    ap.add_argument("--skip-groq", action="store_true",
                    help="skip LLM augmentation (saves 2-3 h; Gujlish falls back "
                         "to app.ml.romanize)")
    ap.add_argument("--epochs", type=int, default=3)
    args = ap.parse_args()

    py = sys.executable
    t0 = time.time()

    if not args.no_install:
        run("1/6 base dependencies", [py, "-m", "pip", "install", "-r", "requirements.txt"])
        ensure_torch()
        run("1/6 ML dependencies", [py, "-m", "pip", "install", "-r", "requirements-ml.txt"])
        try:
            import torch
            if not torch.cuda.is_available():
                print("  note: torch is running on CPU. If this machine has an NVIDIA "
                      "GPU, reinstall with:\n        pip install torch --index-url "
                      "https://download.pytorch.org/whl/cu128 --force-reinstall")
        except ImportError:
            pass

    run("2/6 download raw public datasets (kaggle.com + huggingface.co + github.com)",
        [py, "-m", "app.ml.download_datasets"])

    # Optional Groq augmentation for ALL 5 language forms (needs GROQ_API_KEY
    # in backend/.env): labels the real Gujlish parallel pairs, translates the
    # real Gujarati rows into colloquial Gujlish, and converts real labeled
    # rows into Gen-Z English / casual Hindi / Gujarati / Hinglish registers.
    # Soft step — without a key (or on API failure) Gujlish falls back to
    # app.ml.romanize and the run continues either way.
    from app.config import settings
    if args.skip_groq:
        print("\n(2b/6 skipped: --skip-groq)")
    elif settings.GROQ_API_KEY:
        import os
        print("\n--- 2b/6 Groq augmentation (all 5 language forms) ---")
        print("    ~14k rows via the Groq free tier: expect 2-3 h (rate-limited).")
        print("    Fully resumable — finished rows are cached, re-run to continue.")
        print("    Skip it with --skip-groq (Gujlish then uses the romanize "
              "fallback).", flush=True)
        if subprocess.run([py, "-m", "app.ml.groq_augment"],
                          env=dict(os.environ, PYTHONIOENCODING="utf-8")).returncode != 0:
            print("  (Groq augmentation failed — continuing without it)")
    else:
        print("\n(2b/6 skipped: GROQ_API_KEY not set — no LLM augmentation; "
              "Gujlish uses the romanize fallback. Free key: console.groq.com)")

    if not args.skip_threat:
        run("3/6 fine-tune MuRIL threat classifier",
            [py, "-m", "app.ml.train"])
    else:
        print("\n(3/6 threat classifier skipped)")

    run("4/6 fine-tune MuRIL sentiment model on the raw datasets",
        [py, "-m", "app.ml.train_sentiment", "--epochs", str(args.epochs)])

    run("5/6 TF-IDF + LinearSVC sentiment baseline",
        [py, "-m", "app.ml.train_baseline"])

    if not args.skip_threat:
        run("6/6 evaluate the threat pipeline",
            [py, "-m", "app.ml.evaluate"])

    print(f"\nAll artifacts rebuilt in {(time.time() - t0) / 60:,.1f} min:")
    print("  app/data/datasets/                  raw public datasets (as published)")
    print("  app/ml/models/threat-classifier/    fine-tuned MuRIL (4 threat classes)")
    print("  app/ml/models/sentiment-classifier/ fine-tuned MuRIL (neg/neu/pos, 5 language forms)")
    print("  app/ml/sentiment_eval_report.json   per-language accuracy / macro-F1")
    print("  app/ml/baseline_report.json         classical baseline for comparison")
    print("  app/ml/eval_report.json             threat pipeline metrics")
    print("\nStart the app — the models are picked up automatically (NLP_MODE=full).")


if __name__ == "__main__":
    main()
