<div align="center">

# 🛡️ SENTINEL

### Social Media Threat & Sentiment Analyzer

**Real-time OSINT threat intelligence for law-enforcement analysts** — monitoring
coordinated misinformation, communal-tension instigation, threats against
office-holders and organized cyberbullying across Facebook, Instagram, Reddit,
X and YouTube (all via official platform APIs), with first-class NLP for
**Gujarati, Hindi, Hinglish, Gujlish and English** — the exact segment generic
moderation misses. Deployment scope: **Surat, Ahmedabad, Vadodara, Rajkot**
(configurable via `TARGET_CITIES`).

`git clone` → **one command** → raw datasets downloaded, both models trained,
live multilingual threat-intelligence dashboard. **Zero API keys required.**

</div>

---

## ⚡ Quick start (TL;DR)

```bash
git clone <your-repo-url>
cd E-Rakshak-Sentiment-Analysis/backend

python -m venv .venv
.venv\Scripts\activate            # Windows   (source .venv/bin/activate on Linux/macOS)

python -m app.ml.bootstrap        # ⬅ THE one command: deps + all 22 datasets + both trained models
cd .. && .\run.ps1                # or ./run.sh — starts backend + frontend
```

Open **http://localhost:5173** → *Enter Dashboard* → sign in. API docs: http://localhost:8000/docs.

| | |
|---|---|
| Username | `suratpolice` |
| Password | `Suratpolice@1234` |

That account is provisioned on first boot with the **admin** role, which is what
unlocks the **Admin Panel** in the sidebar. It is a *known* credential — it lives
in `backend/app/config.py`, which lives in this repository — so the server warns
about it at every boot and Admin Panel → Security Posture flags it until you
change it. Set `BOOTSTRAP_ADMIN_PASSWORD` in `backend/.env` before this instance
holds real case data, or change the password from Admin Panel → Officers.

Full walkthrough (where `.env` goes, which keys, what bootstrap does):
[§ You just cloned the repo](#-you-just-cloned-the-repo--do-exactly-this).

**Just want to see the UI?** Skip bootstrap — `.\run.ps1` alone starts the app
immediately (it serves generic pretrained models until you train the fine-tuned ones).

> **How is this possible with zero keys?** SENTINEL ships a *simulated ingestion
> mode* (the default): a labeled, template-driven generator producing realistic
> Gujarati/Hindi/Hinglish/English posts — including coordinated bot bursts — that
> flow through the **identical** pipeline real API data would. Add keys to `.env`
> and real platform adapters activate automatically alongside or instead of it.

---

## 🚀 You just cloned the repo — do exactly this

Git does **not** ship the datasets, the trained models, the venv or the secrets
(they're gitignored — too big or secret). **One command rebuilds all of it and
trains everything.**

### Prerequisites

| Tool | Version | Check |
|---|---|---|
| Python | 3.11 – 3.13 | `python --version` |
| Node.js | 18+ | `node --version` |
| Git | any | `git --version` |
| (optional) NVIDIA GPU | any CUDA card | training is ~5× faster; CPU works too |

### Step 1 — Clone and create the venv

```bash
git clone <your-repo-url>
cd E-Rakshak-Sentiment-Analysis/backend

python -m venv .venv
.venv\Scripts\activate           # Windows PowerShell
# source .venv/bin/activate      # Linux / macOS
```

### Step 2 — Create `backend/.env` (optional, but do it for the full build)

The file goes at **`backend/.env`** — same folder as `requirements.txt`, right
next to `app/`. It is gitignored, so **it never arrives with a `git pull` —
every teammate creates their own.** Create it and paste this in:

```env
# NLP engine: full = trained MuRIL models | lite = lexicon fallback
NLP_MODE=full

# Zero-key demo stream (leave true unless you have live platform keys)
SIMULATION_ENABLED=true
TARGET_CITIES=Surat,Ahmedabad,Vadodara,Rajkot

# ── the ONE key that matters for training ─────────────────────────────
# Free, 30 seconds to get: https://console.groq.com → API Keys → Create
# Used to (a) LLM-augment the training data for all 5 language forms and
# (b) double-check risky posts at runtime. Without it everything still
# works — you just skip the augmentation layer.
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# ── live platform APIs: OPTIONAL, not needed for the demo or training ──
X_BEARER_TOKEN=
YOUTUBE_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
```

**Which keys do you actually need?**

| Key | Needed for | Required? |
|---|---|---|
| *(none)* | downloading all 22 datasets + training both models | ✅ **works with zero keys** — Kaggle/HF/GitHub downloads are anonymous |
| `GROQ_API_KEY` | LLM data augmentation (Gen-Z / Hindi / Gujarati / Hinglish / Gujlish) + runtime verification | ⭐ recommended — **free** at [console.groq.com](https://console.groq.com) |
| `X_BEARER_TOKEN`, `YOUTUBE_API_KEY`, `REDDIT_*`, `FB_*`, `IG_*` | pulling **real live posts** instead of the simulated stream | ❌ optional — see [§ Going live](#-going-live-with-real-platform-apis) |

### Step 3 — The one command: every ignored file + full training

```bash
# from backend/, venv active
python -m app.ml.bootstrap
```

That single command, in order:

1. installs the base + ML dependencies (CUDA torch when a GPU is present),
2. **downloads all 22 raw public datasets** from kaggle.com, huggingface.co and
   github.com into `backend/app/data/datasets/` (~400 MB, original
   CSV/parquet/CoNLL files, **no API keys needed**),
3. **[only if `GROQ_API_KEY` is set]** LLM-augments the training data for all
   five language forms → `datasets/groq-augmented/` (~14k rows),
4. fine-tunes the **MuRIL sentiment model** → `app/ml/models/sentiment-classifier/`,
5. fine-tunes the **MuRIL sentiment model** → `app/ml/models/sentiment-classifier/`,
6. trains the TF-IDF baseline and writes every eval report.

**How long?** ~1 hour on a GPU without a Groq key. **With** a Groq key add
**2–3 hours** for the augmentation — Groq's free tier is rate-limited. That step
is fully resumable (finished rows are cached; just re-run to continue), and
`--skip-groq` opts out of it entirely.

| Flag | Effect |
|---|---|
| `--skip-groq` | skip LLM augmentation (saves 2–3 h; Gujlish falls back to `romanize.py`) |
| `--no-install` | dependencies already installed |
| `--skip-threat` | only rebuild datasets + the sentiment model |
| `--epochs N` | sentiment fine-tune epochs (default 3) |

### Step 4 — Run the app

```bash
# from the repo root
.\run.ps1        # Windows
./run.sh         # Linux / macOS
```

Installs frontend packages, starts backend (**:8000**) + frontend (**:5173**),
opens the browser. Stop with `Ctrl+C` in each terminal. The SQLite DB persists
between runs — delete `backend/sentinel.db` for a fresh seed.

---

## 📦 What's NOT in git (and what restores it)

| Ignored path | What it is | How it comes back |
|---|---|---|
| `backend/app/data/datasets/` | **the 22 raw public datasets** (Kaggle + HF + GitHub, original files) | `python -m app.ml.bootstrap` — ✅ auto |
| **`backend/app/ml/models/`** | **the fine-tuned MuRIL models** (threat + sentiment) | `python -m app.ml.bootstrap` retrains them — ✅ auto |
| `.../datasets/groq-augmented/` | LLM-augmented training rows | `python -m app.ml.bootstrap` (needs `GROQ_API_KEY`) — ✅ auto |
| `backend/app/ml/*_report.json`, `backend/reports/*.pdf` | eval reports, generated PDFs | recreated by bootstrap / eval / report runs — ✅ auto |
| `backend/.venv/`, `frontend/node_modules/` | installed dependencies | `pip install` / `npm install` (bootstrap + run scripts do this) — ✅ auto |
| **`backend/.env`** | **your config + secret API keys** | **⚠️ manual — create it yourself** (Step 2); it is *never* in git |

The app **runs even without the trained models** — full mode falls back to
generic pretrained models, then to the lite lexicon engine, so nothing crashes.
Training is seeded, so every teammate who runs bootstrap gets the same model.

> **Alternative to retraining:** to share the exact model files, use
> [Git LFS](https://git-lfs.com/) on `backend/app/ml/models/`, or zip that folder
> to a cloud drive. For a hackathon, retraining is the least error-prone option.

---

## 🏗️ Architecture

```
┌─ Collectors ────────────┐   ┌─ NLP Pipeline ─────────────┐   ┌─ Intelligence ──────────┐
│ Simulated stream (dflt) │   │ normalize (slang/translit) │   │ trend + spike detection │
│ Facebook Graph API      │   │ language ID (gu/hi/hing/en)│   │ network centrality      │
│ Instagram Graph API     │ → │ 3-model sentiment vote     │ → │ bot-cluster detection   │
│ Reddit OAuth API        │   │ sentiment + intent         │   │ alerting + escalation   │
│ X API v2 · YouTube v3   │   │ toxicity + hate flags      │   │ report generation (PDF) │
│ generic Web/RSS         │   │ composite concern score    │   │ per-city geo-tagging    │
│  (APScheduler loop with │   │ Groq LLM verification      │   │                         │
│   per-API politeness    │   │                            │   │                         │
│   gaps — never hammered)│   │                            │   │                         │
└─────────────────────────┘   └────────────────────────────┘   └─────────────────────────┘
           ↓                              ↓                    ↓
        SQLite/Postgres (SQLModel)  →  FastAPI REST + WebSocket /ws/live
                                             ↓
              React + Vite + TS · Tailwind · GSAP · Recharts · d3-force canvas
```

**Backend** `backend/app/`: `crawlers/` (adapter per platform), `ml/` (NLP core +
dataset download, corpus assembly, training, evaluation), `services/` (ingestion,
scheduler, trends, network, reports, Groq verifier, WS hub), `routers/` (REST + WS),
`models/`+`schemas/` (SQLModel/Pydantic).
**Frontend** `frontend/src/`: `services/api.ts` (every backend call, typed) +
`services/ws.ts` (reconnecting live socket), `pages/`, `components/`, `hooks/`, `data/`.

---

## 🧠 NLP pipeline

Two engines, one interface — chosen by `NLP_MODE` in `backend/.env`:

| | `full` (default) | `lite` (fallback) |
|---|---|---|
| Sentiment — model 1 | **fine-tuned google/muril-base-cased** sentiment head, trained on **50k rows from 22 real public datasets** across English/Hindi/Gujarati/Hinglish/Gujlish (`ml/models/sentiment-classifier/`), else **cardiffnlp/twitter-xlm-roberta-base-sentiment** | — |
| Sentiment — model 2 | **TF-IDF (word 1-2 + char 2-5) + LinearSVC** on the same corpus (`ml/models/sentiment-linear/`) | — |
| Sentiment — model 3 | **VADER-style rule engine** (ported from cjhutto/vaderSentiment, extended to Hindi/Gujarati: negation incl. postpositional "accha *nahi*", boosters "bahut/ekdam/khub", ALL-CAPS & !!! emphasis) plus contrast resolution, irony inversion and reported-speech damping | same (always runs) |
| Final check | **Groq LLM** reads the post after the three models and can overturn a confident disagreement | skipped without `GROQ_API_KEY` |
| Toxicity / hate flags | **unitary/multilingual-toxic-xlm-roberta** | abuse lexicons + signal rules |
| Language ID + code-mixing | Unicode-script analysis + romanized marker wordlists (5-way: en/hi/gu/hinglish/gujlish) | same (shared) |
| Setup | `pip install -r requirements-ml.txt` (+ model downloads on first run) | zero downloads, <1 ms/post |

Both paths share normalization (URL/mention stripping, stretch-char collapse,
romanized-slang canonicalization: `nhi→nahi`, `jla do→jala do`), batched
inference, singleton model loading at startup, and graceful per-call fallback
from full → lite so the demo can never break.

**Labels** — exactly what the UI shows, and the whole taxonomy:
`negative` · `neutral` · `positive`.

The system does **not** classify posts as incitement, propaganda or
misinformation. Whether a post will cause violence, and whether a claim inside
it is false, are investigative conclusions about the world; a model reading one
post's words cannot establish either, and a console that prints them as model
output invites an analyst to treat a guess as a finding. Where an external fact
matters, the post detail shows news corroboration from **named** sources
(Google News RSS, GNews, NewsAPI.org) and lets the analyst judge it.

### Context

All three models are fed the same context-tagged input, at training time and at
inference time (`app/ml/context.py`):

```
[ctx1 rep cond long] Officials said the bridge would be repaired if funds are approved
[ctx1 self shout emph short] I waited THREE HOURS at the RTO office!!!
```

The tags are derived from the post text alone — which is what makes them usable
on the training corpora, which are plain (text, label) rows with no metadata —
so the models *learn* what "reported speech" or "interrogative" implies instead
of being handed a flag they never saw. Account, reach and amplification are
known only at inference, so they never touch the model input: they adjust the
ensemble's **confidence** afterwards, never the label, and every adjustment is
recorded with a reason the drawer displays.

Model artifacts are stamped with the context version they were trained under;
serving a checkpoint that predates it falls back to raw text with a loud warning
rather than silently shifting the input distribution.

### Concern score (0–100)

```
score = 100 × ( 0.50 × negativity × confidence   ← how negative, × how sure
              + 0.22 × toxicity                   ← hate/abuse intensity
              + 0.18 × virality                   ← log-scaled engagement + amplification bonus
              + 0.10 × term_severity )            ← strongest lexicon term matched

negativity: max(0, −sentiment_score)  — a positive post contributes 0 here
virality:   min(1, log10(1 + likes + 3·shares + 2·comments + views/50) / 4)  (+0.15 in a burst)
bands:      ≥74 → critical alert + auto-generated escalation packet · ≥65 → high · ≥50 → elevated
```

The weights are shaped so no single dimension can reach an alert band alone: a
furious post nobody read tops out near 50, and a viral cheerful post cannot pass
~30. An alert therefore always means **negative *and* travelling**.

---

## 📊 Measured accuracy (the judging criterion)

### Sentiment — 5 languages, measured on REAL held-out data

Fine-tuned MuRIL vs the classical baseline, on **5,768 held-out rows the model
never saw** (real posts only — LLM-augmented rows are training-only, so these
numbers are honest):

| Language (test n) | **MuRIL** accuracy | **MuRIL** macro-F1 | TF-IDF + LinearSVC accuracy |
|---|---|---|---|
| English (2,000) | **0.698** | 0.692 | 0.603 |
| Hindi (1,144) | **0.741** | 0.728 | 0.670 |
| Hinglish (1,800) | **0.620** | 0.622 | 0.613 |
| Gujarati (229) | **0.878** | 0.719 | 0.734 |
| Gujlish (595) | **0.859** | 0.840 | 0.751 |
| **Overall (5,768)** | **0.706** | **0.703** | 0.640 |

The transformer beats the classical baseline by **+6.6 accuracy points**
(0.706 vs 0.640) — that delta is the evidence it earns its cost.

```bash
cd backend
python -m app.ml.eval_sentiment    # re-run this table any time
python -m app.ml.train_baseline    # re-run the baseline comparison
```

### End-to-end pipeline

```bash
cd backend && python -m app.ml.evaluate
```

Scores the whole pipeline — three models, consensus and context calibration —
against held-out rows, reporting precision/recall/F1 per sentiment label.

The dashboard also shows **live accuracy**: every simulated post carries its
ground-truth sentiment, and `/api/stats` compares it against the pipeline's
prediction in real time (the pipeline never sees the label).

> *Honest caveat:* the threat test set is generated from the same template
> families as its training data (with disjoint slot fills), so treat that 100%
> as a pipeline sanity benchmark, not a field accuracy. The **sentiment** model,
> by contrast, is trained and measured on real public datasets — those numbers
> are the meaningful ones.

---

## 📚 The sentiment corpus: 22 REAL public datasets, zero intermediates

Datasets are downloaded **from kaggle.com, huggingface.co and github.com in
their original file formats** (CSV / parquet / gzipped-JSONL / CoNLL, original
filenames) into `backend/app/data/datasets/`. Training reads those raw files
**directly** (`app/ml/corpus.py`) and assembles the corpus **in memory** — no
merged JSON is ever written. Full provenance table with links:
[`backend/app/data/datasets/README.md`](backend/app/data/datasets/README.md).

Coverage is deliberate: not just five languages, but every **register** a real
feed contains — Gen-Z / gamer slang, brainrot-era social media, Indian political
Twitter, plain conversation, and formal long-form reviews.

| Language | Real sources |
|---|---|
| English | **Kaggle:** Sentiment140 (Stanford, 1.6M tweets, raw 227 MB CSV) · Twitter-airline · **twitter-entity (75k gaming tweets — Gen-Z/gamer slang)** · IMDB 50k · social-media multi-platform (emoji/hashtag posts) — **HF:** tweet_eval (SemEval-2017) · **GoEmotions** (58k Reddit comments) · boltuix emotions (131k casual texts) · Sp1786 multiclass |
| Hindi | Cardiff tweet_sentiment_multilingual-hindi · AI4Bharat IndicSentiment-hi · OdiaGenAI reviews · sepidmnorozy + Process-Venue movie reviews |
| Gujarati | AI4Bharat IndicSentiment-gu · nikitadesai Gujarati movie reviews (the only real public Gujarati sentiment data that exists) |
| Hinglish | **SemEval-2020 Task 9 SentiMix** (the reference Hinglish corpus, 17k, from raw CoNLL) · Hinglish YouTube comments · Kaggle Indian Twitter+Reddit rows our detector flags as code-mixed · code-mixed tweet sets |
| Gujlish | **GitHub: mukund302002/Gujlish-English-Translation** — the only real Gujlish corpus anywhere (30k parallel pairs + 300 social-media sentences), sentiment-labeled from its English side by the LLM |

The corpus build also reports **Gen-Z slang coverage**: how many of the 1,550
terms in the MLBtrio slang dictionary (also downloaded raw) appear in training —
currently **546**.

```bash
cd backend
python -m app.ml.download_datasets   # raw datasets → app/data/datasets/
python -m app.ml.corpus              # inspect the corpus (per language / per source / slang coverage)
python -m app.ml.train_sentiment     # fine-tune MuRIL (GPU ~45 min, fp16 auto)
python -m app.ml.train_baseline      # TF-IDF + LinearSVC on the same corpus (minutes)
python -m app.ml.rescore             # replay stored posts through the new models

# Both trained models consume the same context-tagged input, so they must be
# retrained together — an ensemble where one saw the discourse prefix and the
# other did not is two models reading different things. Each artifact records
# which context version it was trained under and refuses to be served a
# distribution it never saw.
```

### 🤖 LLM data augmentation (all 5 languages)

Public data has holes: there is **no labeled Gen-Z corpus**, **no sentiment-labeled
Gujlish corpus**, and barely 1.4k real Gujarati rows on the entire internet. With a
free `GROQ_API_KEY`, `python -m app.ml.groq_augment` fills them — **converting real
labeled rows into the missing register/language**, never inventing labels:

| Target | What it does | Rows |
|---|---|---|
| `gujlish-pairs` | sentiment-labels the **real** Gujlish sentences (from the GitHub corpus) using their English side; only confidence ≥ 0.8 kept | 3,667 |
| `genz` | rewrites real English rows in Gen-Z / brainrot register — label preserved | 2,436 |
| `gujarati` | translates real rows to casual Gujarati — label preserved | 2,328 |
| `hinglish` | translates real rows to code-mixed Hinglish — label preserved | 2,314 |
| `hindi` | translates real rows to casual social-media Hindi — label preserved | 1,942 |
| `gujlish` | translates the real Gujarati rows to colloquial Gujlish ("che", "bau") | 1,544 |

Guardrails: the labels always come from the real datasets (the LLM only changes
language/register); the register conversions are **training-only**; and source rows
are sampled from the train split, so nothing test-derived can leak into training.
The **held-out test set stays real**. Without a key, Gujlish falls back to the
mechanical transliterator (`app/ml/romanize.py`) and the rest simply contributes nothing.

**Did it work?** Gujlish macro-F1 went **0.626 → 0.840** and Gujarati accuracy
**0.860 → 0.878** after augmentation, and Gujlish is now measured against 366
*real* Gujlish sentences instead of only synthetic ones. Overall: 0.692 → **0.706**.

---

## 🕸️ Network & campaign detection

Runs generically on any data (not just the simulator):

1. **Near-duplicate clustering** — word-3-gram Jaccard similarity + union-find
   over recent non-neutral posts catches copy-paste amplification.
2. **Cluster scoring** — synchronized posting windows, account age, follower
   counts, templated handle prefixes, machine-generated handle detection
   (digit runs / random-string analysis) → a confidence score **plus
   human-readable "why flagged" evidence** shown in the UI (e.g. *"6 accounts
   posted near-identical text within 2m 55s · average account age 23 days ·
   handles share a templated prefix"*).
3. **Graph** — networkx degree centrality sizes nodes (influence), average
   concern score colors them, bot-suspect accounts get dashed red rings.

Trends use sliding-window term velocity with **z-score spike detection** per
hashtag/keyword, language breakdown, and per-city threat heat for Gujarat —
rendered on a **live SVG geo map of Gujarat** (marker size = post volume,
color = average threat, pulsing rings on hot regions; self-contained
projection, no tile servers).

### LLM verification layer (optional)

With a free `GROQ_API_KEY`, a second-opinion reviewer
(`services/groq_verifier.py`) audits every risky post **before alerts fire**:
one batched JSON-mode request asks the LLM to independently classify
threat + sentiment. Agreement raises the model's confidence; a confident
disagreement (LLM ≥ 0.75) overrides the label and recomputes the concern score
with the same formula. Nothing is silent — the verdict, reason, and an
`overridden` flag are stored per post and shown in the analyst UI. Without a
key the layer is a no-op, and any API failure degrades to "unverified".

---

## 🔌 API surface

| Endpoint | Purpose |
|---|---|
| `GET /api/stats` | KPIs, sparklines, distributions, live accuracy |
| `GET /api/feed` | filters: platform, language, threat_level, location, q, min_score, date range · sort · pagination (server-side) |
| `GET /api/feed/{id}` · `POST /api/feed/{id}/escalate` | full NLP breakdown · analyst escalation |
| `GET /api/trends?hours=` | hashtags/keywords + spike z-scores, languages, regions |
| `GET /api/network?hours=` | nodes/links/flagged clusters |
| `GET /api/alerts` · `POST /api/alerts/{id}/acknowledge` · `/escalate` | alert workflow |
| `GET /api/reports` · `POST /api/reports/generate` · `GET /api/reports/{id}/download` | JSON + PDF reports |
| `GET/POST/PATCH/DELETE /api/watchlist` | keywords/hashtags/accounts/locations steering the crawlers |
| `WS /ws/live` | real-time posts + alerts |
| `POST /api/auth/login` · `/logout` · `/change-password` | session lifecycle (scrypt, per-IP rate limit, per-account lockout) |
| `GET/POST/PATCH/DELETE /api/auth/users` | officer accounts — **admin only** |
| `GET /api/auth/audit` · `/security-posture` | chain-of-custody log · live hardening checklist — **admin only** |
| `POST /api/assistant/ask` · `GET /api/assistant/capabilities` | Sentinel voice assistant (read-only) |

Every router except `/api/health` is authenticated at the *router* level, so a
route added later is protected by default rather than public until someone
remembers a decorator.

---

## 🎙️ Sentinel — the voice assistant

Sign in and **just talk** — “tell me the trends in Surat”. There is no wake word
and nothing to switch on: the channel opens when the dashboard loads, reopens
itself if it drops, and the orb bottom right is for reading the transcript or
cutting an answer short. It briefs the last 24 hours, reads out critical alerts
as they arrive, gives per-city threat levels, names the highest-scoring post,
breaks activity down by platform, and navigates the dashboard.

Talking over an answer stops it mid-sentence. It does not hear itself: while the
assistant is audible not one microphone frame is sent, and the browser tells the
server exactly when its speakers go quiet — which is not when the server
finished *sending* audio, and mistaking the two is what makes a voice agent
transcribe its own reply and answer it (`services/voice/state.py`).

A microphone is live in a room full of people and cannot tell who is speaking,
so the boundary is structural rather than a prompt asking a model to behave
(`backend/app/routers/assistant.py`):

- **Read-only by construction.** Every answer comes from a fixed query in that
  module. No handler writes. Acknowledging alerts, editing the watchlist,
  resetting passwords and purging data are not reachable from the router at all.
- **Protected subjects are refused before intent matching** — officer accounts,
  credentials, the audit trail, biometrics and the suspect registry — so a mixed
  request (“show alerts *and* list all officers”) refuses whole rather than
  answering the half it liked. Refusals are audit-logged.
- **The LLM never sees crawled post text.** Post text is authored by the accounts
  under investigation; feeding it to an instruction-following model an officer
  then trusts is a prompt-injection channel. The fallback model gets aggregate
  counts only, and cannot trigger navigation or any action.
- Its own rate-limit budget, separate from the analyst's.

Wake-word mode is **off by default**: in Chrome and Edge the Web Speech API
streams audio to the vendor's cloud, which the UI says out loud rather than
burying. Typing works identically with no microphone at all.

---

## 🔒 Security posture

Admin Panel → **Security Posture** evaluates the live configuration and tells you
what is still weak — default password in use, unset `SECRET_KEY`, HSTS off,
biometrics unencrypted, SQLite instead of a durable database. What is already in
place:

| Layer | Control |
|---|---|
| Passwords | scrypt (memory-hard, stdlib), self-describing hashes, transparent rehash on login |
| Sign-in | one generic error for every failure, dummy-hash verify so timing does not leak either, per-IP rate limit **and** per-account lockout |
| Sessions | short-lived bearer tokens, `token_version` revokes every issued token at once (logout, role change, deactivation), sessionStorage so a shared terminal does not keep a session, idle auto-logout with a warning |
| Authorisation | three ranks, "at least this rank" checks, enforced server-side on every call |
| Audit | append-only in the *database* — `BEFORE UPDATE OR DELETE` triggers on SQLite and Postgres — with actor, badge, IP and user-agent denormalised at write time |
| Transport | strict CORS allowlist (`*` refused at startup), Host-header allowlist, CSP generated per-deployment, `nosniff` / `DENY` / `no-referrer` / `Permissions-Policy`, optional HSTS |
| Abuse | sliding-window rate limits in three separate budgets (default, expensive, assistant), request body ceiling, SSRF guard on outbound OSINT fetches |
| Leakage | unhandled errors log the trace and return a generic 500; `/api/health` describes nothing about the deployment |

---

## 🔑 Going live with real platform APIs

Every live adapter uses the platform's **official API** — no scraping, no proxy
tricks. Collection follows the **seed-source strategy**: instead of crawling the
open web, each platform monitors the top public sources for the target cities
(news pages, civic bodies, city subreddits), plus the analyst watchlist. An
optional `:City` suffix on any seed geo-tags everything it produces; posts
without a tag are geo-tagged from city mentions in the text (English / Hindi /
Gujarati spellings).

Add any of these to `backend/.env`:

```env
# Facebook Graph API — seed pages per city (page id or username)
FB_ACCESS_TOKEN=...
FB_PAGE_IDS=tv9gujarati:Ahmedabad,SuratMunicipalCorporation:Surat,VMCVadodara:Vadodara

# Instagram Graph API — business discovery + watchlist hashtag search
IG_ACCESS_TOKEN=...
IG_BUSINESS_ACCOUNT_ID=...           # your linked IG professional account id
IG_SEED_USERNAMES=amdavadamc:Ahmedabad,suratsmartcity:Surat

# Reddit OAuth API (script app) — city subreddits + watchlist search
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_SUBREDDITS=Surat:Surat,ahmedabad:Ahmedabad,Vadodara:Vadodara,rajkot:Rajkot,Gujarat

X_BEARER_TOKEN=...        # X API v2 recent search
YOUTUBE_API_KEY=...       # YouTube Data API v3
RSS_FEEDS=https://example.com/feed.xml,...   # local news outlets
```

### Instagram without a Meta app review

Instagram business discovery needs a reviewed Meta app, which not every
deployment has. The **`Instagram (instagrapi)`** adapter is the fallback: it
drives Instagram's private mobile API with a real account session, and it runs
only while `IG_ACCESS_TOKEN` is unset — dropping a Graph token into `.env`
upgrades the source in place, with no duplicate ingestion and nothing else to
change.

```env
IG_USERNAME=...          # a dedicated burner account, never a personal one
IG_PASSWORD=...
IG_SESSIONID=...         # preferred: the sessionid cookie from a logged-in browser
```

```bash
cd backend && python -m app.crawlers.instagrapi_login            # one-time login
cd backend && python -m app.crawlers.instagrapi_login --verify   # prove it works
```

The login handshake lives in that command rather than in the crawl loop because
Instagram answers a fresh login from an unfamiliar IP with a checkpoint, and
answering one needs a console. The resulting session is saved to
`backend/ig_session.json` (gitignored — it is full account access) and reused
unattended afterwards. If Instagram insists on its *native* challenge flow, no
Python client can clear it: log in once in a normal browser, complete the
prompt there, and copy that tab's `sessionid` cookie into `IG_SESSIONID` —
that route skips the login handshake entirely and is the least likely to be
challenged.

Four things are fetched per cycle, each answering a different question:

| leg | what it reads | why |
|---|---|---|
| **posts** | recent media from `IG_SEED_USERNAMES` | what the city is announcing |
| **hashtags** | media matching watchlist tags | what the city is saying |
| **users** | media from watchlist `account` rows, plus the real profile behind an author found via a hashtag | a watched handle was otherwise monitored only by accident; hashtag media carries no follower count at all, so a viral stranger was scored as having zero reach |
| **comments** | the thread under the most-commented media | on a municipal page the caption is a press release and the grievance is thirty comments down |

Every leg is budgeted and rotates: `IG_HASHTAGS_PER_CYCLE`,
`IG_WATCHED_ACCOUNTS_PER_CYCLE`, `IG_PROFILE_LOOKUPS_PER_CYCLE` and
`IG_COMMENTS_MAX_MEDIA_PER_CYCLE` cap the private-API calls per cycle, and each
cycle resumes where the last stopped so the whole watchlist gets covered over
the day rather than the first few entries every time. Private-API reads get an
account blocked far faster than Graph calls do, hence the wider
`IG_MIN_INTERVAL_SECONDS` (default 1800 s) — keep volumes low and leave the

politeness gaps alone.

Restart — each configured adapter activates automatically and its posts flow
through the identical NLP → scoring → alerting → reporting pipeline. The
watchlist (editable in the UI) becomes the live crawl query. Set
`SIMULATION_ENABLED=false` to go fully live. Swap SQLite for **Supabase** (or any
Postgres) with one `DATABASE_URL` — tables, migrations and the append-only audit
triggers are all created on boot: [docs/SUPABASE.md](docs/SUPABASE.md), which
also covers migrating an existing SQLite corpus across. Every setting worth
overriding is annotated in [backend/.env.example](backend/.env.example); the
rest have defaults in `backend/app/config.py`.

**API etiquette (important):** the scheduler enforces a per-platform politeness
gap — no live API is queried more often than `CRAWL_MIN_INTERVAL_SECONDS`
(default 300 s, YouTube 900 s because a search costs 100 quota units), and
adapters sleep ~1 s between the individual queries inside one batch. Rapid-fire
requests against a single endpoint look like abuse and get the app/IP blocked —
batch, then wait.

*Meta app notes:* reading Facebook pages you don't manage requires the **Page
Public Content Access** feature (app review); Instagram business discovery and
hashtag search require a linked **Instagram professional account**, and Meta caps
hashtag search at 30 unique hashtags per week (the adapter queries only the first
few watchlist hashtags per cycle and caches hashtag ids).

---

## 📁 Data provenance & content note

**Sentiment** is trained on **real public datasets only** — 6 raw Kaggle
datasets, 15 Hugging Face corpora (including the official SemEval-2020 SentiMix
Hinglish benchmark, GoEmotions and AI4Bharat IndicSentiment) and 1 GitHub corpus
(the only real Gujlish data in existence), all kept as raw files under
`backend/app/data/datasets/` and read directly at training time. Labels are never
invented: LLM augmentation only converts the language/register of rows that
already carry a real label. Full table: [`backend/app/data/datasets/README.md`](backend/app/data/datasets/README.md).

The **simulator** corpus (`backend/app/data/templates.py`) is synthetic,
written for this project across 4 languages × 4 categories, using deliberately
generic group references and fictional office-holders — no real public
hate-speech dataset covers these exact 4 operational categories.

---

<div align="center">
<sub>Built for the E-Rakshak hackathon · FastAPI · SQLModel · APScheduler · networkx ·
React · Vite · TypeScript · Tailwind · GSAP · Recharts · d3-force</sub>
</div>
