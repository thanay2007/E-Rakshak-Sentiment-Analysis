# -*- coding: utf-8 -*-
"""Download the RAW public sentiment datasets E-Rakshak trains on.

This script only DOWNLOADS — it writes no processed/merged files. Every
dataset is kept in its original file format (CSV / parquet / CoNLL txt),
exactly as published, under:

    app/data/datasets/kaggle/<dataset>/<original files>       (kaggle.com)
    app/data/datasets/huggingface/<org>/<dataset>/<files>     (huggingface.co)
    app/data/datasets/github/<repo>/<original files>          (github.com)

Training (app.ml.corpus) reads these raw files directly — there is no
intermediate JSON corpus. Delete a folder and re-run this script to get a
pristine copy.

The corpus spans the 5 language forms the platform monitors (English, Hindi,
Gujarati, Hinglish, Gujlish) and every register judges will care about:
Gen-Z / gamer slang, brainrot-era social-media language, plain conversational
text, product/movie reviews (older-demographic language) and Indian political
Twitter/Reddit.

Usage (from backend/):   python -m app.ml.download_datasets
Needs: pip install -r requirements-ml.txt   (kagglehub + huggingface_hub)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings

DATASETS_DIR = settings.DATA_DIR / "datasets"
KAGGLE_DIR = DATASETS_DIR / "kaggle"
HF_DIR = DATASETS_DIR / "huggingface"

# ── kaggle.com datasets (anonymous download via kagglehub) ──────────────────
# (handle, files to keep — None = keep every file in the dataset)
KAGGLE_DATASETS: list[tuple[str, list[str] | None]] = [
    # English — the Stanford 1.6M-tweet classic (all-ages Twitter language)
    ("kazanova/sentiment140", ["training.1600000.processed.noemoticon.csv"]),
    # English — 14.6k airline tweets (complaints/praise, normal adult register)
    ("crowdflower/twitter-airline-sentiment", ["Tweets.csv"]),
    # English — 75k tweets about games/brands (Borderlands, FIFA, CS-GO … the
    # Gen-Z / gamer-slang register)
    ("jp797498e/twitter-entity-sentiment-analysis",
     ["twitter_training.csv", "twitter_validation.csv"]),
    # English/Hinglish — 200k Indian political tweets + reddit comments
    ("cosmos98/twitter-and-reddit-sentimental-analysis-dataset",
     ["Twitter_Data.csv", "Reddit_Data.csv"]),
    # English — IMDB 50k long-form movie reviews (formal / older-demographic)
    ("lakshmi25npathi/imdb-dataset-of-50k-movie-reviews", ["IMDB Dataset.csv"]),
    # English — multi-platform posts with emojis + hashtags (Instagram/FB/Twitter)
    ("kashishparmar02/social-media-sentiments-analysis-dataset", None),
]

# ── huggingface.co datasets (raw repo files via snapshot_download) ──────────
HF_DATASETS: list[str] = [
    # English
    "cardiffnlp/tweet_eval",                            # SemEval-2017 Twitter benchmark
    "google-research-datasets/go_emotions",             # 58k Reddit comments (slang-heavy)
    "boltuix/emotions-dataset",                         # 131k casual internet texts
    "Sp1786/multiclass-sentiment-analysis-dataset",     # 31k 3-class posts
    "MLBtrio/genz-slang-dataset",                       # 1.8k Gen-Z slang terms + examples
    # Hindi
    "mteb/tweet_sentiment_multilingual",                # Cardiff tweets (hindi config)
    "mteb/IndicSentiment",                              # AI4Bharat reviews (hi + gu)
    "OdiaGenAI/sentiment_analysis_hindi",               # product reviews
    "sepidmnorozy/Hindi_sentiment",                     # movie reviews
    "Process-Venue/Movie_Review_Sentiment_Hindi",       # annotated reviews
    # Gujarati
    "nikitadesai/gujaratiMovieSentiments",              # 3-class movie reviews
    # Hinglish
    "RTT1/SentiMix",                                    # SemEval-2020 Task 9 (CoNLL)
    "shae2977/hinglish-youtube-sentiments-dataset",     # real YouTube comments
    "Abhishek4896/hindi-english-code-mixed-tweets-sentiment",
    "airzipm/sentiment-dataset-en-hi-hinglish-v2",
]

# ── github.com datasets (raw files) ──────────────────────────────────────────
# (repo, branch, files) — the only real Gujlish corpus anywhere: 30k
# English<->Gujlish parallel pairs + 300 social-media-register sentences
GITHUB_DATASETS: list[tuple[str, str, list[str]]] = [
    ("mukund302002/Gujlish-English-Translation", "main",
     ["English-Gujlish dataset.csv", "Social_media.csv"]),
]


def kaggle_dataset(handle: str, files: list[str] | None) -> Path:
    """Fetch `handle` from kaggle.com (anonymous, public) and keep the raw
    files under datasets/kaggle/<name>/ with their original filenames."""
    dest = KAGGLE_DIR / handle.split("/")[1]
    wanted = files
    if dest.exists() and (wanted is None or all((dest / f).exists() for f in wanted)):
        return dest
    import kagglehub

    src = Path(kagglehub.dataset_download(handle))
    dest.mkdir(parents=True, exist_ok=True)
    src_files = [p for p in src.rglob("*") if p.is_file()]
    if wanted is not None:
        by_name = {p.name: p for p in src_files}
        src_files = [by_name[f] for f in wanted if f in by_name] or src_files
    for p in src_files:
        target = dest / p.name
        if not target.exists():
            shutil.copy2(p, target)
    return dest


def hf_dataset(repo_id: str) -> Path:
    """Snapshot the raw data files of a Hugging Face dataset repo into
    datasets/huggingface/<org>/<name>/ (original parquet/csv/txt files).

    Downloads via the default short HF cache first, then copies — writing
    straight into this (deep) project path can exceed Windows' 260-char
    MAX_PATH limit for the transfer's temp files."""
    dest = HF_DIR / repo_id
    from huggingface_hub import snapshot_download

    snap = Path(snapshot_download(
        repo_id,
        repo_type="dataset",
        ignore_patterns=["*.py", ".gitattributes", "*.lock"],
    ))
    for p in snap.rglob("*"):
        if not p.is_file():
            continue
        target = dest / p.relative_to(snap)
        if not target.exists() or target.stat().st_size != p.stat().st_size:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    return dest


def github_dataset(repo: str, branch: str, files: list[str]) -> Path:
    """Fetch raw files of a GitHub repo into datasets/github/<name>/."""
    import urllib.parse

    import httpx

    dest = DATASETS_DIR / "github" / repo.split("/")[1]
    dest.mkdir(parents=True, exist_ok=True)
    for fname in files:
        target = dest / fname
        if target.exists() and target.stat().st_size > 0:
            continue
        url = (f"https://raw.githubusercontent.com/{repo}/{branch}/"
               f"{urllib.parse.quote(fname)}")
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            target.write_bytes(resp.content)
    return dest


def _tree_size(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file() and ".cache" not in p.parts]
    return len(files), sum(p.stat().st_size for p in files)


def main() -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str]] = []

    print("── kaggle.com ──────────────────────────────────────────────")
    for handle, files in KAGGLE_DATASETS:
        try:
            dest = kaggle_dataset(handle, files)
            n, size = _tree_size(dest)
            results.append((f"kaggle.com/{handle}", f"{n} files, {size / 1e6:,.1f} MB"))
            print(f"  [ok]   {handle}  ({n} files, {size / 1e6:,.1f} MB)")
        except Exception as exc:
            results.append((f"kaggle.com/{handle}", f"FAILED: {exc}"))
            print(f"  [SKIP] {handle}: {exc}")

    print("── huggingface.co ──────────────────────────────────────────")
    for repo_id in HF_DATASETS:
        try:
            dest = hf_dataset(repo_id)
            n, size = _tree_size(dest)
            results.append((f"hf.co/datasets/{repo_id}", f"{n} files, {size / 1e6:,.1f} MB"))
            print(f"  [ok]   {repo_id}  ({n} files, {size / 1e6:,.1f} MB)")
        except Exception as exc:
            results.append((f"hf.co/datasets/{repo_id}", f"FAILED: {exc}"))
            print(f"  [SKIP] {repo_id}: {exc}")

    print("── github.com ──────────────────────────────────────────────")
    for repo, branch, files in GITHUB_DATASETS:
        try:
            dest = github_dataset(repo, branch, files)
            n, size = _tree_size(dest)
            results.append((f"github.com/{repo}", f"{n} files, {size / 1e6:,.1f} MB"))
            print(f"  [ok]   {repo}  ({n} files, {size / 1e6:,.1f} MB)")
        except Exception as exc:
            results.append((f"github.com/{repo}", f"FAILED: {exc}"))
            print(f"  [SKIP] {repo}: {exc}")

    failed = [r for r in results if r[1].startswith("FAILED")]
    print(f"\n{len(results) - len(failed)}/{len(results)} datasets in {DATASETS_DIR}")
    for name, info in failed:
        print(f"  !! {name}: {info}")
    print("Next: python -m app.ml.train_sentiment   (trains straight from the raw files)")


if __name__ == "__main__":
    main()
