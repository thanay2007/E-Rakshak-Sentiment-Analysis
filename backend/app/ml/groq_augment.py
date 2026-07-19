# -*- coding: utf-8 -*-
"""Groq LLM data augmentation for ALL five language forms
(free key: console.groq.com -> GROQ_API_KEY in backend/.env).

Every target starts from REAL labeled rows of the raw public datasets — the
LLM only converts language/register, never invents labels, so sentiment
supervision stays real:

  genz        real English rows rewritten as Gen-Z / brainrot social-media
              English ("fr", "no cap", "mid", emojis) — label preserved
  hindi       real English rows translated to casual social-media Hindi
              (Devanagari) — label preserved
  gujarati    real English rows translated to casual Gujarati (Gujarati
              script) — label preserved (real Gujarati data is scarce: ~1.4k)
  hinglish    real English/Hindi rows translated to romanized code-mixed
              Hinglish — label preserved
  gujlish     real Gujarati rows translated to colloquial Gujlish
              ("che", "bau", natural English mixing) — label preserved
  gujlish-pairs
              the REAL Gujlish sentences from github.com/mukund302002/
              Gujlish-English-Translation (30k pairs + 300 social-media
              sentences): the LLM sentiment-labels each pair from its
              ENGLISH side; only confident (>= 0.8) labels are kept

Source rows are sampled from the TRAIN split only (seed 13 — the same split
training uses), so nothing derived from a test row can reach training.
Output CSVs live with the other datasets in app/data/datasets/groq-augmented/
and app.ml.corpus picks them up automatically (translation targets are used
for TRAINING ONLY; the held-out test set stays real). Without a key, Gujlish
falls back to app.ml.romanize and the other targets simply contribute nothing.

Idempotent + resumable: re-running skips finished rows, so a rate-limit abort
just continues later.

Usage (from backend/):
    python -m app.ml.groq_augment                     # every target
    python -m app.ml.groq_augment --target genz       # one target
    python -m app.ml.groq_augment --target gujlish-pairs --limit 2000
Then retrain:  python -m app.ml.train_sentiment
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from collections import Counter

import httpx

from app.config import settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OUT_DIR = settings.DATA_DIR / "datasets" / "groq-augmented"
PAIRS_DIR = settings.DATA_DIR / "datasets" / "github" / "Gujlish-English-Translation"

BATCH = 12            # posts per request (keeps completions inside token limits)
SLEEP_S = 2.5         # politeness gap between requests (free-tier RPM/TPM)
MAX_CHARS = 450       # long reviews are truncated; MuRIL reads 128 tokens anyway

_JSON_RULE = ('Reply ONLY with JSON: {"results": [{"id": <id>, "text": "..."}, ...]} '
              "— one entry per input, same ids. No explanations, no quotes.")

_PROMPTS = {
    "genz": (
        "You rewrite social-media posts in Gen-Z internet English — casual slang "
        "('fr', 'no cap', 'lowkey', 'mid', 'ate', 'goated', 'rizz', 'based', "
        "'it's giving...'), occasional emojis, texting style. Use slang naturally, "
        "not every word. Preserve the meaning and the emotional tone EXACTLY — "
        "do not soften, strengthen, add or drop opinions.\n" + _JSON_RULE),
    "hindi": (
        "You translate social-media posts into casual Hindi exactly as typed on "
        "Indian social media, in Devanagari script. Everyday spoken Hindi, not "
        "formal shuddh Hindi; well-known English words (phone, movie, traffic) "
        "may stay in Latin script. Preserve the meaning and the emotional tone "
        "EXACTLY.\n" + _JSON_RULE),
    "gujarati": (
        "You translate social-media posts into casual Gujarati exactly as typed "
        "on Indian social media, in Gujarati script. Everyday spoken Gujarati, "
        "not formal; well-known English words may stay in Latin script. Preserve "
        "the meaning and the emotional tone EXACTLY.\n" + _JSON_RULE),
    "hinglish": (
        "You translate social-media posts into HINGLISH — romanized Hindi mixed "
        "naturally with English words, exactly as young Indians type online "
        "('yaar', 'bahut', 'nahi', 'kya baat hai'). Latin script only, casual "
        "spelling. Keep it Hindi-dominant. Preserve the meaning and the "
        "emotional tone EXACTLY.\n" + _JSON_RULE),
    "gujlish": (
        "You convert Gujarati social-media posts into GUJLISH — romanized "
        "Gujarati exactly as young Indians type it online. Latin script only, "
        "casual spelling ('che'/'chhe', 'nathi', 'maja', 'ekdam', 'bau'), mix in "
        "common English words ONLY where a real user naturally would. Keep it "
        "Gujarati-dominant. Preserve the meaning and the emotional tone "
        "EXACTLY.\n" + _JSON_RULE),
}

_LABEL_SYSTEM = (
    "You label the sentiment of English sentences. For EACH sentence give:\n"
    "- label: negative | neutral | positive\n"
    "- confidence: 0.0-1.0\n"
    "Factual/descriptive statements with no expressed opinion are neutral.\n"
    'Reply ONLY with JSON: {"results": [{"id": <id>, "label": ..., '
    '"confidence": ...}, ...]} — one entry per sentence, same ids.'
)


# ── script validators: the output must actually be the target language ──────

def _latin_ratio(t: str) -> float:
    return sum(c.isascii() and c.isalpha() for c in t) / max(len(t), 1)


def _script_ratio(t: str, lo: int, hi: int) -> float:
    return sum(lo <= ord(c) <= hi for c in t) / max(len(t), 1)


_VALIDATORS = {
    "genz": lambda t: _latin_ratio(t) >= 0.5,
    "hindi": lambda t: _script_ratio(t, 0x0900, 0x097F) >= 0.3,       # Devanagari
    "gujarati": lambda t: _script_ratio(t, 0x0A80, 0x0AFF) >= 0.3,    # Gujarati
    "hinglish": lambda t: _latin_ratio(t) >= 0.5,
    "gujlish": lambda t: _latin_ratio(t) >= 0.5,
}

# corpus lang tag each target trains as
_TARGET_LANG = {"genz": "English", "hindi": "Hindi", "gujarati": "Gujarati",
                "hinglish": "Hinglish", "gujlish": "Gujlish"}
_DEFAULT_CAPS = {"genz": 2500, "hindi": 2500, "gujarati": 2500,
                 "hinglish": 2500, "gujlish": 0, "gujlish-pairs": 4000}  # 0 = all

# Groq rate limits are PER MODEL, so each target defaults to its own model —
# this lets targets run in parallel on fresh quotas instead of queueing on one
# drained model. Override with --model.
_TARGET_MODELS = {
    "gujlish-pairs": "llama-3.1-8b-instant",  # easy labeling task, big quota
    "genz": "openai/gpt-oss-20b",
    "gujlish": "openai/gpt-oss-120b",       # strongest fresh model for the hard target
    "gujarati": "openai/gpt-oss-120b",
    "hindi": "openai/gpt-oss-20b",
    "hinglish": "llama-3.1-8b-instant",
}
MODEL = settings.GROQ_MODEL                  # set per-target in main()


def _body(messages: list[dict], temperature: float) -> dict:
    body = {"model": MODEL, "temperature": temperature,
            "response_format": {"type": "json_object"}, "messages": messages}
    if MODEL.startswith("openai/"):          # gpt-oss: don't burn TPM on reasoning
        body["reasoning_effort"] = "low"
    return body


# ── source-row sampling (train split only — no test leakage) ────────────────

def _sample_balanced(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Label-balanced sample of short, social-register rows."""
    short = [r for r in rows if len(r["text"]) <= 220]
    by_label: dict[str, list] = {"negative": [], "neutral": [], "positive": []}
    for r in short:
        by_label[r["label"]].append(r)
    for pool in by_label.values():
        rng.shuffle(pool)
    out, i = [], 0
    while len(out) < n and any(by_label.values()):
        lab = ("negative", "neutral", "positive")[i % 3]
        i += 1
        if by_label[lab]:
            out.append(by_label[lab].pop())
    return out


def source_rows(target: str, cap: int) -> list[dict]:
    from app.ml.corpus import load_corpus, load_gujarati_movies, load_indic

    rng = random.Random(4242)
    if target == "gujlish":
        # ALL real Gujarati rows (both loader pools) — corpus.synthesize maps
        # each split's rows through the cache, so split integrity is kept there
        rows: list[dict] = []
        for tr, te in (load_indic(rng, "gu", "Gujarati"), load_gujarati_movies(rng)):
            rows += tr + te
        seen, out = set(), []
        for r in rows:
            if r and r["text"] not in seen:
                seen.add(r["text"])
                out.append(r)
        return out

    train, _ = load_corpus(seed=13, verbose=False)      # TRAIN split only
    src_langs = {"genz": ("English",), "hindi": ("English",),
                 "gujarati": ("English",), "hinglish": ("English", "Hindi")}[target]
    pool = [r for r in train
            if r["lang"] in src_langs and not r["source"].startswith(("romanized", "groq"))]
    return _sample_balanced(pool, cap or 2500, rng)


# ── Groq plumbing ────────────────────────────────────────────────────────────

def _extract(content: str) -> list[dict]:
    """Pull the result rows out of a completion. Models disagree on shape:
    some return {"results": [...]}, some a bare [...], some wrap the list under
    another key — accept all of them."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", content, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("results")
        if not isinstance(rows, list):          # any other single list value
            rows = next((v for v in data.values() if isinstance(v, list)), [])
    else:
        return []
    return [r for r in rows if isinstance(r, dict)]


def _post(client: httpx.Client, body: dict) -> list[dict]:
    """One Groq chat-completion with retry/backoff; returns the result rows.
    A batch that cannot be salvaged returns [] (its rows stay un-cached and are
    simply retried on the next run) — one bad batch never kills the job."""
    for attempt in range(5):
        try:
            resp = client.post(GROQ_URL, json=body, headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            })
        except httpx.HTTPError as exc:       # timeout / connection drop → retry
            print(f"    {type(exc).__name__} — retrying in 15s ...", flush=True)
            time.sleep(15)
            continue

        if resp.status_code == 200:
            return _extract(resp.json()["choices"][0]["message"]["content"])

        if resp.status_code in (429, 500, 502, 503):
            # cap the honored retry-after: a huge value (daily-quota style)
            # would otherwise sleep for hours with no feedback
            wait = min(float(resp.headers.get("retry-after", 15 * (attempt + 1))), 120.0)
            print(f"    HTTP {resp.status_code} — waiting {wait:.0f}s ...", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code == 400 and "json_validate_failed" in resp.text:
            # the model emitted invalid JSON — salvage what it did produce,
            # then move on. Skipped rows are picked up by the next run.
            try:
                failed = resp.json()["error"].get("failed_generation", "")
            except Exception:
                failed = ""
            rows = _extract(failed)
            print(f"    HTTP 400 json_validate_failed — salvaged {len(rows)} rows",
                  flush=True)
            return rows

        if resp.status_code in (401, 402, 403):
            raise RuntimeError(
                f"Groq HTTP {resp.status_code} (auth/quota): {resp.text[:200]}\n"
                "Check GROQ_API_KEY / your Groq plan. Finished rows are cached — "
                "re-run to resume.")

        print(f"    HTTP {resp.status_code}: {resp.text[:120]} — skipping batch",
              flush=True)
        return []
    print("    retries exhausted — skipping batch (will retry on next run)", flush=True)
    return []


def _done_originals(path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8", newline="") as f:
        return {r["original"] for r in csv.DictReader(f)}


# ── translation / register-rewrite targets ──────────────────────────────────

def run_translate_target(target: str, limit: int) -> None:
    out_csv = OUT_DIR / f"{target}.csv"
    cap = limit or _DEFAULT_CAPS[target]
    rows = source_rows(target, cap)
    done = _done_originals(out_csv)
    todo = [r for r in rows if r["text"] not in done]
    if limit:                        # explicit --limit = max new rows this run
        todo = todo[:limit]
    elif cap and target != "gujlish":     # default caps are corpus-total targets
        todo = todo[: max(0, cap - len(done))]
    print(f"[{target}] {len(rows)} source rows | {len(done)} cached | {len(todo)} to do")
    if not todo:
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_file = not out_csv.exists()
    validator = _VALIDATORS[target]
    sent = kept = 0
    with open(out_csv, "a", encoding="utf-8", newline="") as f, \
            httpx.Client(timeout=max(settings.GROQ_TIMEOUT_SECONDS, 60)) as client:
        writer = csv.DictWriter(f, fieldnames=["original", "text", "label",
                                               "lang", "source"])
        if new_file:
            writer.writeheader()
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            body = _body([
                {"role": "system", "content": _PROMPTS[target]},
                {"role": "user", "content": json.dumps(
                    {"posts": [{"id": i, "text": r["text"][:MAX_CHARS]}
                               for i, r in enumerate(batch)]}, ensure_ascii=False)},
            ], temperature=0.3)
            results = {int(x["id"]): str(x.get("text", "")) for x in _post(client, body)
                       if str(x.get("id", "")).lstrip("-").isdigit()}
            for i, r in enumerate(batch):
                t = re.sub(r"\s+", " ", results.get(i, "")).strip()
                if len(t) >= 8 and t != r["text"] and validator(t):
                    writer.writerow({"original": r["text"], "text": t,
                                     "label": r["label"],
                                     "lang": _TARGET_LANG[target],
                                     "source": f"groq-{target}({r['source']})"})
                    kept += 1
            f.flush()
            sent += len(batch)
            print(f"  [{target}] {sent}/{len(todo)} sent, {kept} kept", flush=True)
            if start + BATCH < len(todo):
                time.sleep(SLEEP_S)
    print(f"[{target}] wrote {kept} rows -> {out_csv}")


# ── gujlish-pairs labeling target ────────────────────────────────────────────

def gujlish_pairs(rng: random.Random) -> list[dict]:
    """Real Gujlish sentences + their English side, social-media set first."""
    pairs = []
    social = PAIRS_DIR / "Social_media.csv"
    big = PAIRS_DIR / "English-Gujlish dataset.csv"
    if not social.exists() and not big.exists():
        raise SystemExit(f"{PAIRS_DIR} missing — run  python -m app.ml.download_datasets  first.")
    if social.exists():
        with open(social, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                g, e = str(r.get("Gujlish", "")).strip(), str(r.get("English", "")).strip()
                if len(g) >= 8 and e:
                    pairs.append({"gujlish": g, "english": e, "source": "GujlishPairs-social"})
    rest = []
    if big.exists():
        with open(big, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                g, e = str(r.get("guj", "")).strip(), str(r.get("src", "")).strip()
                if len(g) >= 8 and e:
                    rest.append({"gujlish": g, "english": e, "source": "GujlishPairs-general"})
    rng.shuffle(rest)
    seen, out = set(), []
    for p in pairs + rest:
        if p["gujlish"] not in seen:
            seen.add(p["gujlish"])
            out.append(p)
    return out


def run_label_pairs(limit: int) -> None:
    out_csv = OUT_DIR / "gujlish_labeled_pairs.csv"
    rng = random.Random(13)
    pairs = gujlish_pairs(rng)
    done_keys = set()
    if out_csv.exists():
        with open(out_csv, encoding="utf-8", newline="") as f:
            done_keys = {r["gujlish"] for r in csv.DictReader(f)}
    todo = [p for p in pairs if p["gujlish"] not in done_keys]
    todo = todo[: limit or _DEFAULT_CAPS["gujlish-pairs"]]
    print(f"[gujlish-pairs] {len(pairs)} real pairs | {len(done_keys)} labeled | {len(todo)} to do")
    if not todo:
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_file = not out_csv.exists()
    sent = kept = 0
    with open(out_csv, "a", encoding="utf-8", newline="") as f, \
            httpx.Client(timeout=max(settings.GROQ_TIMEOUT_SECONDS, 60)) as client:
        writer = csv.DictWriter(f, fieldnames=["gujlish", "english", "label",
                                               "confidence", "source"])
        if new_file:
            writer.writeheader()
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            body = _body([
                {"role": "system", "content": _LABEL_SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"sentences": [{"id": i, "text": p["english"][:MAX_CHARS]}
                                   for i, p in enumerate(batch)]}, ensure_ascii=False)},
            ], temperature=0)
            for item in _post(client, body):
                try:
                    i = int(item["id"])
                    lab = str(item.get("label", "")).strip().lower()
                    conf = float(item.get("confidence", 0))
                except (KeyError, TypeError, ValueError):
                    continue
                if 0 <= i < len(batch) and lab in ("negative", "neutral", "positive") \
                        and conf >= 0.8:
                    p = batch[i]
                    writer.writerow({"gujlish": p["gujlish"], "english": p["english"],
                                     "label": lab, "confidence": round(conf, 2),
                                     "source": p["source"]})
                    kept += 1
            f.flush()
            sent += len(batch)
            print(f"  [gujlish-pairs] {sent}/{len(todo)} sent, {kept} kept", flush=True)
            if start + BATCH < len(todo):
                time.sleep(SLEEP_S)
    print(f"[gujlish-pairs] wrote {kept} labeled REAL Gujlish rows -> {out_csv}")


ALL_TARGETS = ["gujlish-pairs", "gujlish", "hinglish", "gujarati", "hindi", "genz"]


def main() -> None:
    global MODEL

    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=ALL_TARGETS, nargs="+",
                    help="run these targets only (default: all)")
    ap.add_argument("--limit", type=int, default=0, help="process at most N rows")
    ap.add_argument("--model", help="force one Groq model for every target")
    args = ap.parse_args()

    if not settings.GROQ_API_KEY:
        raise SystemExit(
            "GROQ_API_KEY is empty in backend/.env — get a free key at "
            "console.groq.com, set it, and re-run  python -m app.ml.groq_augment\n"
            "(Until then Gujlish falls back to app.ml.romanize and the other "
            "augmentation targets contribute nothing.)")

    targets = args.target if args.target else ALL_TARGETS
    for t in targets:
        MODEL = args.model or _TARGET_MODELS.get(t, settings.GROQ_MODEL)
        print(f"\n=== target {t}  (model: {MODEL}) ===", flush=True)
        if t == "gujlish-pairs":
            run_label_pairs(args.limit)
        else:
            run_translate_target(t, args.limit)

    counts = Counter()
    for p in OUT_DIR.glob("*.csv"):
        with open(p, encoding="utf-8", newline="") as f:
            counts[p.name] = sum(1 for _ in csv.DictReader(f))
    print("\nAugmentation caches:", dict(counts))
    print("Retrain to use them:  python -m app.ml.train_sentiment")


if __name__ == "__main__":
    main()
