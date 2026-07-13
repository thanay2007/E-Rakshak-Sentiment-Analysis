# -*- coding: utf-8 -*-
"""Build the multilingual sentiment training corpus IN MEMORY, straight from
the raw dataset files downloaded by app.ml.download_datasets.

No intermediate JSON/JSONL is ever written: every training run re-reads the
original CSV / parquet / JSONL / CoNLL files under app/data/datasets/
(kaggle/ and huggingface/, kept exactly as published), normalizes them to
{"text", "label", "lang", "source"} rows with labels in {negative, neutral,
positive}, de-duplicates, applies per-language caps and returns seeded,
reproducible train/test splits.

Language forms covered (lang field): English, Hindi, Gujarati, Hinglish,
Gujlish. Gujlish has no public corpus anywhere, so its rows are the real
Gujarati rows transliterated by app.ml.romanize (the standard augmentation
for zero-resource code-mixed languages); everything else is real posts.

Registers covered: Gen-Z / gamer slang (gaming tweets, GoEmotions Reddit
comments — coverage against the MLBtrio slang dictionary is reported),
emoji/hashtag social-media posts, YouTube + Reddit comments, Indian
political Twitter, plain conversation, and formal long-form reviews
(IMDB, product/movie reviews — the older-demographic register).

Usage:
    from app.ml.corpus import load_corpus
    train_rows, test_rows = load_corpus(seed=13)

    python -m app.ml.corpus        # print per-language/per-source stats
"""
from __future__ import annotations

import csv
import gzip
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from app.config import settings
from app.ml.language import detect_language
from app.ml.romanize import romanize

if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATASETS_DIR = settings.DATA_DIR / "datasets"
KAGGLE_DIR = DATASETS_DIR / "kaggle"
HF_DIR = DATASETS_DIR / "huggingface"

LABELS = ("negative", "neutral", "positive")
_012 = {0: "negative", 1: "neutral", 2: "positive"}

# per-language caps: generous (real data preferred), but bounded so no single
# language drowns the rest and a single-GPU fine-tune stays feasible
TRAIN_CAPS = {"English": 18000, "Hindi": 9000, "Hinglish": 15000,
              "Gujarati": 6000, "Gujlish": 6000}
TEST_CAPS = {"English": 2000, "Hindi": 1200, "Hinglish": 1800,
             "Gujarati": 600, "Gujlish": 800}

csv.field_size_limit(10_000_000)   # IMDB reviews exceed the default field cap


# ── raw-file readers ─────────────────────────────────────────────────────────

def _need(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — run  python -m app.ml.download_datasets  first.")
    return path


def _read_csv(path: Path, encoding: str = "utf-8", header: bool = True):
    with open(_need(path), encoding=encoding, newline="", errors="ignore") as f:
        yield from (csv.DictReader(f) if header else csv.reader(f))


def _read_parquet(path: Path):
    import pandas as pd

    return pd.read_parquet(_need(path))


def _read_jsonl_gz(path: Path) -> list[dict]:
    with gzip.open(_need(path), "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _row(text: str, label: str, lang: str, source: str) -> dict | None:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) < 8 or label not in LABELS:
        return None
    return {"text": text, "label": label, "lang": lang, "source": source}


def _split(rows: list, rng: random.Random, frac: float = 0.1) -> tuple[list, list]:
    rows = [r for r in rows if r]
    rng.shuffle(rows)
    cut = max(1, int(len(rows) * frac))
    return rows[cut:], rows[:cut]


# ═════════════════════════════ English ══════════════════════════════════════

def load_sentiment140(rng) -> tuple[list, list]:
    """Kaggle kazanova/sentiment140 — raw 1.6M-row CSV: label 0/4 in col 0,
    text in col 5, latin-1, no header; the file is label-sorted so a strided
    sample stays balanced without loading 227 MB into RAM."""
    path = KAGGLE_DIR / "sentiment140" / "training.1600000.processed.noemoticon.csv"
    m = {"0": "negative", "4": "positive"}
    rows = []
    for i, r in enumerate(_read_csv(path, encoding="latin-1", header=False)):
        if i % 100 == 0 and len(r) >= 6 and r[0] in m:
            rows.append((r[5], m[r[0]]))
    rng.shuffle(rows)
    out = [_row(t, lab, "English", "Kaggle-Sentiment140") for t, lab in rows[:8000]]
    return _split(out, rng)


def load_airline(rng) -> tuple[list, list]:
    """Kaggle crowdflower/twitter-airline-sentiment — raw Tweets.csv."""
    rows = [_row(r.get("text", ""), str(r.get("airline_sentiment", "")).strip().lower(),
                 "English", "Kaggle-USAirline")
            for r in _read_csv(KAGGLE_DIR / "twitter-airline-sentiment" / "Tweets.csv")]
    return _split(rows, rng)


def load_twitter_gaming(rng) -> tuple[list, list]:
    """Kaggle jp797498e/twitter-entity-sentiment-analysis — 75k tweets about
    games/brands (Borderlands, FIFA, CS-GO …), the Gen-Z gamer-slang register.
    No header: id, entity, sentiment, text. 'Irrelevant' rows are dropped."""
    d = KAGGLE_DIR / "twitter-entity-sentiment-analysis"

    def parse(fname):
        out = []
        for r in _read_csv(d / fname, header=False):
            if len(r) >= 4:
                lab = str(r[2]).strip().lower()
                if lab in LABELS:
                    out.append(_row(r[3], lab, "English", "Kaggle-TwitterGaming"))
        return out

    train = [r for r in parse("twitter_training.csv") if r]
    rng.shuffle(train)
    return train[:8000], parse("twitter_validation.csv")


def load_india_twitter_reddit(rng) -> tuple[list, list]:
    """Kaggle cosmos98/twitter-and-reddit-sentimental-analysis-dataset —
    Indian political Twitter + Reddit comments (category -1/0/1). Rows are
    routed through our language detector: code-mixed ones become Hinglish."""
    d = KAGGLE_DIR / "twitter-and-reddit-sentimental-analysis-dataset"
    m = {"-1": "negative", "0": "neutral", "1": "positive"}
    picked = []
    for fname, text_col, src, cap in (
            ("Twitter_Data.csv", "clean_text", "Kaggle-IndiaTwitter", 8000),
            ("Reddit_Data.csv", "clean_comment", "Kaggle-IndiaReddit", 6000)):
        got = []
        for r in _read_csv(d / fname):
            v = str(r.get("category", "")).strip()
            if v.endswith(".0"):
                v = v[:-2]
            if v in m:
                got.append((r.get(text_col, ""), m[v], src))
        rng.shuffle(got)
        picked.extend(got[:cap])
    rows = []
    for text, lab, src in picked:
        lang = "Hinglish" if detect_language(str(text))[0] == "Hinglish" else "English"
        rows.append(_row(text, lab, lang, src))
    return _split(rows, rng)


def load_imdb(rng) -> tuple[list, list]:
    """Kaggle lakshmi25npathi/imdb-dataset-of-50k-movie-reviews — long-form
    reviews, the formal / older-demographic register."""
    rows = []
    for r in _read_csv(KAGGLE_DIR / "imdb-dataset-of-50k-movie-reviews" / "IMDB Dataset.csv"):
        lab = str(r.get("sentiment", "")).strip().lower()
        text = re.sub(r"<[^>]+>", " ", str(r.get("review", "")))[:600]
        rows.append(_row(text, lab, "English", "Kaggle-IMDB"))
    rng.shuffle(rows)
    return _split(rows[:4000], rng)


def load_social_media_multi(rng) -> tuple[list, list]:
    """Kaggle kashishparmar02/social-media-sentiments-analysis-dataset —
    Instagram/Facebook/Twitter posts full of emojis + hashtags. The Sentiment
    column mixes polarities and fine-grained emotions; both are mapped."""
    d = KAGGLE_DIR / "social-media-sentiments-analysis-dataset"
    path = next(d.glob("*.csv"), d / "sentimentdataset.csv")
    pos = {"positive", "joy", "happiness", "happy", "love", "excitement", "gratitude",
           "admiration", "contentment", "hopeful", "hope", "pride", "euphoria",
           "amusement", "enjoyment", "inspiration", "elation", "affection"}
    neg = {"negative", "anger", "sadness", "sad", "fear", "disgust", "frustration",
           "hate", "grief", "despair", "bitterness", "loneliness", "regret",
           "disappointment", "jealousy", "anxiety", "bad", "betrayal"}
    rows = []
    for r in _read_csv(path):
        lab = str(r.get("Sentiment", "")).strip().lower()
        lab = "positive" if lab in pos else "negative" if lab in neg else \
              "neutral" if lab == "neutral" else None
        if lab:
            rows.append(_row(r.get("Text", ""), lab, "English", "Kaggle-SocialMultiPlatform"))
    return _split(rows, rng)


def load_tweet_eval(rng) -> tuple[list, list]:
    """cardiffnlp/tweet_eval "sentiment" — SemEval-2017 Twitter benchmark
    (raw parquet under tweet_eval/sentiment/)."""
    d = HF_DIR / "cardiffnlp" / "tweet_eval" / "sentiment"

    def parse(fname, cap=None):
        df = _read_parquet(d / fname)
        out = [_row(t, _012.get(int(l), ""), "English", "TweetEval-2017")
               for t, l in zip(df["text"], df["label"])]
        out = [r for r in out if r]
        rng.shuffle(out)
        return out[:cap] if cap else out

    return parse("train-00000-of-00001.parquet", 10000), \
        parse("test-00000-of-00001.parquet", 2000)


# GoEmotions sentiment grouping (from the GoEmotions paper); ambiguous
# emotions (confusion/curiosity/realization/surprise) are skipped.
_GO_NAMES = ["admiration", "amusement", "anger", "annoyance", "approval", "caring",
             "confusion", "curiosity", "desire", "disappointment", "disapproval",
             "disgust", "embarrassment", "excitement", "fear", "gratitude", "grief",
             "joy", "love", "nervousness", "optimism", "pride", "realization",
             "relief", "remorse", "sadness", "surprise", "neutral"]
_GO_POS = {"admiration", "amusement", "approval", "caring", "desire", "excitement",
           "gratitude", "joy", "love", "optimism", "pride", "relief"}
_GO_NEG = {"anger", "annoyance", "disappointment", "disapproval", "disgust",
           "embarrassment", "fear", "grief", "nervousness", "remorse", "sadness"}


def load_go_emotions(rng) -> tuple[list, list]:
    """google-research-datasets/go_emotions ("simplified") — 58k Reddit
    comments: the modern Reddit slang register. Single-label rows only."""
    d = HF_DIR / "google-research-datasets" / "go_emotions" / "simplified"

    def parse(fname, cap=None):
        out = []
        for t, labels in zip(*(lambda df: (df["text"], df["labels"]))(_read_parquet(d / fname))):
            labels = list(labels)
            if len(labels) != 1:
                continue
            name = _GO_NAMES[int(labels[0])]
            lab = "positive" if name in _GO_POS else "negative" if name in _GO_NEG \
                else "neutral" if name == "neutral" else None
            if lab:
                out.append(_row(t, lab, "English", "GoEmotions-Reddit"))
        out = [r for r in out if r]
        rng.shuffle(out)
        return out[:cap] if cap else out

    return parse("train-00000-of-00001.parquet", 8000), \
        parse("test-00000-of-00001.parquet", 1200)


def load_boltuix_emotions(rng) -> tuple[list, list]:
    """boltuix/emotions-dataset — 131k casual internet/conversation texts,
    13 emotions mapped to polarity (sarcasm/confusion/surprise skipped)."""
    df = _read_parquet(HF_DIR / "boltuix" / "emotions-dataset" / "emotions_dataset.parquet")
    pos = {"happiness", "love", "desire"}
    neg = {"sadness", "anger", "fear", "disgust", "shame", "guilt"}
    rows = []
    for t, l in zip(df["Sentence"], df["Label"]):
        lab = str(l).strip().lower()
        lab = "positive" if lab in pos else "negative" if lab in neg else \
              "neutral" if lab == "neutral" else None
        if lab:
            rows.append(_row(t, lab, "English", "BoltuixEmotions"))
    rng.shuffle(rows)
    return _split(rows[:5000], rng)


def load_sp1786(rng) -> tuple[list, list]:
    """Sp1786/multiclass-sentiment-analysis-dataset — 31k 3-class posts
    (raw train_df/test_df CSVs)."""
    d = HF_DIR / "Sp1786" / "multiclass-sentiment-analysis-dataset"

    def parse(fname, cap=None):
        out = [_row(r.get("text", ""), str(r.get("sentiment", "")).strip().lower(),
                    "English", "Sp1786-multiclass") for r in _read_csv(d / fname)]
        out = [r for r in out if r]
        rng.shuffle(out)
        return out[:cap] if cap else out

    return parse("train_df.csv", 8000), parse("test_df.csv")


# ═════════════════════════════ Hindi ════════════════════════════════════════

def load_cardiff_hindi(rng) -> tuple[list, list]:
    """mteb/tweet_sentiment_multilingual — real Hindi tweets (raw per-language
    jsonl.gz). The file mixes Devanagari and romanized rows, so each row is
    routed through our language detector into Hindi vs Hinglish."""
    d = HF_DIR / "mteb" / "tweet_sentiment_multilingual"
    train, test = [], []
    for split, out in (("train", train), ("validation", train), ("test", test)):
        for r in _read_jsonl_gz(d / split / "hindi.jsonl.gz"):
            lab = _012.get(int(r["label"]))
            lang = "Hinglish" if detect_language(r["text"])[0] == "Hinglish" else "Hindi"
            out.append(_row(r["text"], lab, lang, "CardiffTSM-hi"))
    return train, test


def load_indic(rng, cfg: str, lang: str) -> tuple[list, list]:
    """mteb/IndicSentiment — AI4Bharat product reviews, pos/neg (raw
    per-language jsonl.gz)."""
    d = HF_DIR / "mteb" / "IndicSentiment"
    rows = []
    for split in ("train", "test"):
        for r in _read_jsonl_gz(d / split / f"{cfg}.jsonl.gz"):
            lab = str(r.get("LABEL", "")).strip().lower()
            if lab in ("positive", "negative"):
                rows.append(_row(r.get("INDIC REVIEW", ""), lab, lang,
                                 f"IndicSentiment-{cfg}"))
    rng.shuffle(rows)
    return _split(rows, rng, frac=0.15)


def load_odia_hindi(rng) -> tuple[list, list]:
    """OdiaGenAI/sentiment_analysis_hindi — 2.5k real product reviews
    (raw JSON array, labels pos/neg/neu)."""
    path = _need(HF_DIR / "OdiaGenAI" / "sentiment_analysis_hindi"
                 / "sentiment_analysis_term_train.jsonl")
    data = json.load(open(path, encoding="utf-8"))
    m = {"pos": "positive", "neg": "negative", "neu": "neutral",
         "positive": "positive", "negative": "negative", "neutral": "neutral"}
    rows = [_row(r.get("text", ""), m.get(str(r.get("label", "")).strip().lower(), ""),
                 "Hindi", "OdiaGenAI-hi") for r in data]
    rng.shuffle(rows)
    return _split(rows, rng, frac=0.125)


def load_sepid_hindi(rng) -> tuple[list, list]:
    """sepidmnorozy/Hindi_sentiment — movie reviews, binary 0/1 (raw CSVs)."""
    d = HF_DIR / "sepidmnorozy" / "Hindi_sentiment"
    rows = []
    for fname in ("train.csv", "valid.csv"):
        for r in _read_csv(d / fname):
            v = str(r.get("label", "")).strip()
            if v in ("0", "1"):
                rows.append(_row(r.get("text", ""), "positive" if v == "1" else "negative",
                                 "Hindi", "HindiReviews-sepid"))
    rng.shuffle(rows)
    return _split(rows, rng, frac=0.125)


def load_pv_hindi(rng) -> tuple[list, list]:
    """Process-Venue/Movie_Review_Sentiment_Hindi — 1k annotated reviews. The
    raw CSV's Answer column carries the gold label in Hindi (सकारात्मक /
    नकारात्मक / तटस्थ); मिश्रित (mixed) rows are skipped."""
    d = HF_DIR / "Process-Venue" / "Movie_Review_Sentiment_Hindi"
    path = next(d.glob("*.csv"), None)
    if path is None:
        raise FileNotFoundError(f"no CSV in {d} — run app.ml.download_datasets")
    m = {"सकारात्मक": "positive", "नकारात्मक": "negative", "तटस्थ": "neutral",
         "positive": "positive", "negative": "negative", "neutral": "neutral"}
    rows = []
    for r in _read_csv(path):
        lab = m.get(str(r.get("Answer", "")).strip().lower()
                    if str(r.get("Answer", "")).strip().isascii()
                    else str(r.get("Answer", "")).strip())
        if lab:
            rows.append(_row(r.get("Movie Review's", ""), lab, "Hindi", "ProcessVenue-hi"))
    rng.shuffle(rows)
    return _split(rows, rng, frac=0.125)


# ═════════════════════════════ Gujarati ═════════════════════════════════════

def load_gujarati_movies(rng) -> tuple[list, list]:
    """nikitadesai/gujaratiMovieSentiments — 3-class movie reviews (raw CSV;
    0/1/2 = neg/neu/pos; one stray annotation-guideline row gets skipped)."""
    d = HF_DIR / "nikitadesai" / "gujaratiMovieSentiments"
    path = next(d.glob("*.csv"), None)
    if path is None:
        raise FileNotFoundError(f"no CSV in {d} — run app.ml.download_datasets")
    rows = [_row(r.get("reivew", ""), _012[int(str(r["sentimentGOLD"]).strip())],
                 "Gujarati", "GujaratiMovieReviews")
            for r in _read_csv(path)
            if str(r.get("sentimentGOLD", "")).strip() in {"0", "1", "2"}]
    rng.shuffle(rows)
    return _split(rows, rng, frac=0.125)


# ═════════════════════════════ Hinglish ═════════════════════════════════════

def _detok(tokens: list[str]) -> str:
    out = []
    for t in tokens:
        if out and (t in {".", ",", "!", "?", "…", ":", ";", ")", "’", "'"}):
            out[-1] += t
        elif out and out[-1] in {"@", "#", "("}:
            out[-1] += t
        else:
            out.append(t)
    text = " ".join(out)
    text = re.sub(r"https?\s*//\S*|https?\S*|\btco\s*/\s*\S+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_sentimix(rng) -> tuple[list, list]:
    """RTT1/SentiMix — SemEval-2020 Task 9 Hinglish (raw CoNLL token files,
    reconstructed into sentences here)."""
    d = HF_DIR / "RTT1" / "SentiMix"

    def parse(fname: str) -> list[dict]:
        rows, tokens, label = [], [], None
        for line in open(_need(d / fname), encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if parts[0] == "meta":
                if tokens and label in LABELS:
                    rows.append(_row(_detok(tokens), label, "Hinglish", "SentiMix-2020"))
                tokens, label = [], (parts[2].strip() if len(parts) > 2 else None)
            elif parts[0].strip():
                tokens.append(parts[0])
        if tokens and label in LABELS:
            rows.append(_row(_detok(tokens), label, "Hinglish", "SentiMix-2020"))
        return [r for r in rows if r]

    return parse("train_14k_split_conll.txt"), parse("dev_3k_split_conll.txt")


def load_hinglish_youtube(rng) -> tuple[list, list]:
    """shae2977/hinglish-youtube-sentiments-dataset — real YouTube comments."""
    path = HF_DIR / "shae2977" / "hinglish-youtube-sentiments-dataset" \
        / "yt_hinglish_comments_dataset.csv"
    rows = [_row(r.get("comment", ""), str(r.get("sentiment", "")).strip().lower(),
                 "Hinglish", "HinglishYouTube") for r in _read_csv(path)]
    rng.shuffle(rows)
    return _split(rows, rng, frac=0.125)


def load_codemixed_tweets(rng) -> tuple[list, list]:
    """Abhishek4896/hindi-english-code-mixed-tweets-sentiment (raw CSV)."""
    path = HF_DIR / "Abhishek4896" / "hindi-english-code-mixed-tweets-sentiment" \
        / "hindi_english_code_mixed_tweets_sentiment.csv"
    return [_row(r.get("tweet", ""), str(r.get("sentiment", "")).strip().lower(),
                 "Hinglish", "CodeMixedTweets") for r in _read_csv(path)], []


def load_enhi_hinglish(rng) -> tuple[list, list]:
    """airzipm/sentiment-dataset-en-hi-hinglish-v2 — big mixed dump, kept only
    where OUR language detector says Hinglish."""
    df = _read_parquet(HF_DIR / "airzipm" / "sentiment-dataset-en-hi-hinglish-v2"
                       / "data" / "train-00000-of-00001.parquet")
    kept: list = []
    for t, l in zip(df["text"], df["label"]):
        if len(kept) >= 4000:
            break
        lab = _012.get(int(l), "")
        text = str(t)
        if lab and detect_language(text)[0] == "Hinglish":
            kept.append(_row(text, lab, "Hinglish", "EnHiHinglish-v2"))
    return kept, []


# ═════════════════════════════ Gujlish ══════════════════════════════════════

def load_gujlish_pairs(rng) -> tuple[list, list]:
    """REAL Gujlish sentences from github.com/mukund302002/
    Gujlish-English-Translation, sentiment-labeled from their English side by
    the Groq LLM (python -m app.ml.groq_augment --target gujlish-pairs).
    Optional — contributes nothing until that labeling cache exists."""
    path = DATASETS_DIR / "groq-augmented" / "gujlish_labeled_pairs.csv"
    if not path.exists():
        return [], []
    rows = [_row(r.get("gujlish", ""), str(r.get("label", "")).strip().lower(),
                 "Gujlish", r.get("source", "GujlishPairs"))
            for r in _read_csv(path)]
    rng.shuffle(rows)
    return _split(rows, rng)


def load_groq_augmented(rng) -> tuple[list, list]:
    """Groq register/language conversions of real labeled rows — Gen-Z English
    rewrites plus casual Hindi/Gujarati/Hinglish translations (python -m
    app.ml.groq_augment). Labels come from the real source rows. TRAIN ONLY:
    the held-out test set stays purely real, and sources are sampled from the
    train split so nothing test-derived can leak in. Optional — contributes
    nothing until the caches exist."""
    d = DATASETS_DIR / "groq-augmented"
    rows = []
    for name in ("genz", "hindi", "gujarati", "hinglish"):
        path = d / f"{name}.csv"
        if not path.exists():
            continue
        for r in _read_csv(path):
            rows.append(_row(r.get("text", ""), str(r.get("label", "")).strip().lower(),
                             r.get("lang", ""), r.get("source", f"groq-{name}")))
    rows = [r for r in rows if r and r["lang"] in TRAIN_CAPS]
    rng.shuffle(rows)
    return rows, []


def synthesize(train: list[dict], test: list[dict], rng: random.Random) -> None:
    """Gujlish augmentation from the real Gujarati rows. Preferred: the Groq
    LLM translation cache (colloquial register — python -m app.ml.groq_augment
    --target gujlish); fallback: app.ml.romanize transliteration. Extra
    Hinglish variety is romanized from Devanagari rows."""
    groq_path = DATASETS_DIR / "groq-augmented" / "gujlish.csv"
    groq_cache: dict[str, str] = {}
    if groq_path.exists():
        groq_cache = {r["original"]: r["text"] for r in _read_csv(groq_path)}

    def to_gujlish(r: dict) -> dict | None:
        g = groq_cache.get(r["text"])
        if g:
            return _row(g, r["label"], "Gujlish", f"groq-gujlish({r['source']})")
        t = romanize(r["text"])
        latin = sum(c.isascii() and c.isalpha() for c in t)
        if latin / max(len(t), 1) < 0.5:         # romanization must dominate
            return None
        return _row(t, r["label"], "Gujlish", f"romanized({r['source']})")

    def roman_rows(rows, src_lang, new_lang, cap):
        out = []
        # only REAL native-script rows feed the romanizer — romanizing an
        # LLM-translated row would be a transliteration of a translation
        pool = [r for r in rows
                if r["lang"] == src_lang and not r["source"].startswith("groq-")]
        rng.shuffle(pool)
        for r in pool[:cap]:
            if new_lang == "Gujlish":
                rr = to_gujlish(r)
            else:
                t = romanize(r["text"])
                latin = sum(c.isascii() and c.isalpha() for c in t)
                if latin / max(len(t), 1) < 0.5:
                    continue
                rr = _row(t, r["label"], new_lang, f"romanized({r['source']})")
            if rr:
                out.append(rr)
        return out

    train += roman_rows(train, "Gujarati", "Gujlish", 7000)
    test += roman_rows(test, "Gujarati", "Gujlish", 900)
    train += roman_rows(train, "Hindi", "Hinglish", 2000)


# ═════════════════════════════ assembly ═════════════════════════════════════

LOADERS = [
    ("KAGGLE Sentiment140 (en)", load_sentiment140),
    ("KAGGLE US Airline (en)", load_airline),
    ("KAGGLE Twitter gaming/Gen-Z (en)", load_twitter_gaming),
    ("KAGGLE India Twitter+Reddit (en/hinglish)", load_india_twitter_reddit),
    ("KAGGLE IMDB 50k (en)", load_imdb),
    ("KAGGLE social-media multi-platform (en)", load_social_media_multi),
    ("tweet_eval sentiment (en)", load_tweet_eval),
    ("GoEmotions Reddit (en)", load_go_emotions),
    ("boltuix emotions (en)", load_boltuix_emotions),
    ("Sp1786 multiclass (en)", load_sp1786),
    ("tweet_sentiment_multilingual (hi)", load_cardiff_hindi),
    ("IndicSentiment (hi)", lambda rng: load_indic(rng, "hi", "Hindi")),
    ("IndicSentiment (gu)", lambda rng: load_indic(rng, "gu", "Gujarati")),
    ("OdiaGenAI hindi reviews", load_odia_hindi),
    ("sepidmnorozy Hindi_sentiment", load_sepid_hindi),
    ("Process-Venue hindi movie reviews", load_pv_hindi),
    ("gujaratiMovieSentiments (gu)", load_gujarati_movies),
    ("SentiMix 2020 (hinglish)", load_sentimix),
    ("hinglish-youtube-sentiments", load_hinglish_youtube),
    ("hindi-english code-mixed tweets", load_codemixed_tweets),
    ("en-hi-hinglish-v2 (routed)", load_enhi_hinglish),
    ("REAL Gujlish pairs, Groq-labeled (gujlish)", load_gujlish_pairs),
    ("Groq register/language augmentation (train-only)", load_groq_augmented),
]


def load_corpus(seed: int = 13, verbose: bool = True) -> tuple[list[dict], list[dict]]:
    """Read every raw dataset → normalized, capped, de-duplicated and seeded
    train/test row lists. Deterministic for a given seed + dataset files."""
    rng = random.Random(seed)
    train: list[dict] = []
    test: list[dict] = []
    for name, fn in LOADERS:
        try:
            tr, te = fn(rng)
            tr = [r for r in tr if r]
            te = [r for r in te if r]
            train += tr
            test += te
            if verbose:
                print(f"  [ok]   {name}: {len(tr)} train / {len(te)} test")
        except FileNotFoundError as exc:
            raise SystemExit(str(exc)) from exc
        except Exception as exc:
            if verbose:
                print(f"  [SKIP] {name}: {exc}")

    synthesize(train, test, rng)

    def finalize(rows, caps, seen):
        rng.shuffle(rows)
        kept, quota = [], Counter()
        for r in rows:
            key = r["text"].lower()
            if key in seen or quota[r["lang"]] >= caps.get(r["lang"], 0):
                continue
            seen.add(key)
            quota[r["lang"]] += 1
            kept.append(r)
        rng.shuffle(kept)
        return kept

    seen: set = set()
    test = finalize(test, TEST_CAPS, seen)      # test first → train never leaks into it
    train = finalize(train, TRAIN_CAPS, seen)
    return train, test


def genz_slang_coverage(rows: list[dict]) -> tuple[int, int]:
    """How many terms of the MLBtrio/genz-slang-dataset dictionary appear in
    the corpus — evidence that the slang register is actually covered."""
    path = HF_DIR / "MLBtrio" / "genz-slang-dataset" / "all_slangs.csv"
    if not path.exists():
        return 0, 0
    terms = {str(r.get("Slang", "")).strip().lower() for r in _read_csv(path)}
    terms = {t for t in terms if 1 < len(t) < 25}
    corpus_words = set()
    for r in rows:
        corpus_words.update(re.findall(r"[a-z0-9']+", r["text"].lower()))
    hit = {t for t in terms if " " not in t and t in corpus_words}
    return len(hit), len(terms)


def summarize(train: list[dict], test: list[dict]) -> None:
    stats: dict = {"train": defaultdict(Counter), "test": defaultdict(Counter)}
    for split, rows in (("train", train), ("test", test)):
        for r in rows:
            stats[split][r["lang"]][r["label"]] += 1
    print(f"\n{'lang':<10} {'split':<6} {'neg':>6} {'neu':>6} {'pos':>6} {'total':>7}")
    print("-" * 46)
    for split in ("train", "test"):
        for lang in TRAIN_CAPS:
            c = stats[split][lang]
            print(f"{lang:<10} {split:<6} {c['negative']:>6} {c['neutral']:>6} "
                  f"{c['positive']:>6} {sum(c.values()):>7}")
    srcs = Counter(r["source"] for r in train)
    print(f"\n{len(srcs)} sources: " + ", ".join(f"{s}({n})" for s, n in srcs.most_common()))
    try:
        hit, total = genz_slang_coverage(train)
        if total:
            print(f"Gen-Z slang coverage: {hit}/{total} dictionary terms appear in the corpus")
    except Exception:
        pass


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 13
    tr, te = load_corpus(seed=seed)
    summarize(tr, te)
    print(f"\n{len(tr)} train / {len(te)} test rows (in memory — nothing written)")
