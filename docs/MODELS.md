# SENTINEL — Model Documentation

This document describes every machine-learning model E-Rakshak / SENTINEL uses,
the data each was trained on, how each is evaluated, and how their predictions
are combined and independently verified. All accuracy figures are **measured on
a held-out test split** and are read live by the portal from the evaluation
report JSONs in `backend/app/ml/` — they are not hand-typed.

The portal exposes the same information at **`GET /api/models`** and on the
**Settings → Models** panel, so a reviewer can confirm these numbers in the
running system.

---

## 1. Why three models (the consensus design)

A single model that is wrong is wrong silently. SENTINEL runs **three
independent sentiment models of three different families** on every post; they
vote, and the system chooses the best answer. Because the models fail in
different ways (a rule model trips on sarcasm, a linear model on long-range
context, a transformer on rare slang), their **agreement is real signal** — not
three copies of the same mistake. A fourth layer, a Groq LLM, then
independently double-checks the winning label.

| # | Model | Family | Overall accuracy* | Role |
|---|-------|--------|-------------------|------|
| 1 | MuRIL Transformer | Deep learning (fine-tuned) | **70.6 %** | Primary — context & code-mixing |
| 2 | TF-IDF + LinearSVC | Classical ML | **64.0 %** | Robust second opinion |
| 3 | Multilingual Lexicon | Rule-based | — (zero-shot) | Transparent tie-breaker |
| ✓ | Groq `llama-3.3-70b` | LLM verifier | — | Independent double-check |

\* Overall accuracy on a **5,768-row held-out test set**, 5 languages.

### Decision rule ("the best one is chosen")
1. Each model outputs a **label** (negative / neutral / positive) and a
   **confidence** in [0, 1].
2. **If ≥ 2 models agree**, that label wins (majority). Its confidence is the
   mean of the agreeing models plus a small consensus bonus.
3. **If all three disagree**, the single **most-confident** model wins — the
   "best one," weighted by each model's historical reliability.
4. The numeric sentiment score (−1…+1) is the confidence-weighted average of the
   models backing the winning label, so the score reflects consensus strength.
5. Every model's individual vote and the `chosen_by` reason are **stored on the
   post** and shown to the analyst — the decision is fully auditable.

Implementation: [`backend/app/ml/ensemble.py`](../backend/app/ml/ensemble.py).

---

## 2. Model 1 — MuRIL Transformer (deep learning)

- **Base model:** `google/muril-base-cased` — a 12-layer BERT pre-trained by
  Google on 17 Indian languages (monolingual + parallel + transliterated text).
  Chosen over `ai4bharat/indic-bert` after the latter became a gated repo.
- **Head:** 3-class sentiment classifier, fine-tuned for 3 epochs @ 2e-5.
- **Why it's the primary model:** MuRIL understands *context* and *code-mixing*
  natively — "service saru nathi" (Gujlish: "service is not good") is correctly
  negative even though "saru" ("good") is positive in isolation.
- **Measured accuracy (5,768 test rows):**

  | Language | n | Accuracy | Macro-F1 |
  |----------|---|----------|----------|
  | Overall | 5,768 | **70.6 %** | 0.703 |
  | Gujarati | 229 | 87.8 % | 0.719 |
  | Gujlish | 595 | 85.9 % | 0.840 |
  | Hindi | 1,144 | 74.1 % | 0.728 |
  | English | 2,000 | 69.8 % | 0.692 |
  | Hinglish | 1,800 | 62.0 % | 0.622 |

- **Artifact:** `backend/app/ml/models/sentiment-classifier/` · report:
  `sentiment_eval_report.json`. Retrain: `python -m app.ml.train_sentiment`.

## 3. Model 2 — TF-IDF + LinearSVC (classical ML)

- **Architecture:** a Linear Support-Vector Classifier over TF-IDF features:
  **word n-grams (1–2)** + **character n-grams (2–5)**, ~320k features, with
  `class_weight="balanced"`. LinearSVC was chosen over Naive Bayes / Logistic
  Regression / Random Forest because Linear SVM won head-to-head on this corpus.
- **Why char n-grams matter:** they absorb Hinglish/Gujlish **spelling
  variation** ("bahut / bhut / bohot / bauhat") that a word-only model treats as
  four unrelated tokens — the reason a classical model stays competitive on
  code-mixed Indian text.
- **Confidence:** LinearSVC has no native probabilities; SENTINEL applies a
  **softmax over the one-vs-rest decision-function margins** to give the
  ensemble a calibrated per-class confidence.
- **Trained on the identical corpus** to the transformer, so the accuracy gap is
  an honest measure of what the deep model earns:

  | Language | n | Accuracy | Macro-F1 |
  |----------|---|----------|----------|
  | Overall | 5,768 | **64.0 %** | 0.638 |
  | Gujlish | 595 | 75.1 % | 0.715 |
  | Gujarati | 229 | 73.4 % | 0.595 |
  | Hindi | 1,144 | 67.0 % | 0.655 |
  | Hinglish | 1,800 | 61.3 % | 0.614 |
  | English | 2,000 | 60.3 % | 0.599 |

- **Artifact:** `backend/app/ml/models/sentiment-linear/model.joblib` · report:
  `baseline_report.json`. Train + save: `python -m app.ml.train_baseline`.

## 4. Model 3 — Multilingual Lexicon (rule-based)

- **Method:** a VADER-style valence engine ported from `cjhutto/vaderSentiment`
  and extended to Hindi, Gujarati, Hinglish and Gujlish. Negation flips valence
  ("accha nahi", "saru nathi"), boosters/dampeners scale it ("bahut", "thoda"),
  ALL-CAPS and `!`/`?` runs intensify, and a contrastive conjunction (but /
  lekin / pan) re-weights the following clause. VADER's published constants are
  preserved, so the port is faithful.
- **Why keep it:** it needs **no training**, is **fully explainable** (every
  score traces to matched words — vital for a police audit trail), and catches
  fresh slang the trained models have never seen.
- **Artifact:** none — code + curated lexicons
  ([`backend/app/ml/sentiment.py`](../backend/app/ml/sentiment.py),
  `lexicons.py`).

---

## 5. Concern score (the police-facing number)

There is **no threat classifier.** A post's only tag is its sentiment. The
earlier four-label taxonomy (*Incitement to Violence, Inflammatory, Fake News,
Neutral*) was removed because whether a post will incite violence, and whether a
claim inside it is false, are investigative conclusions about the world — a
model reading one post's words establishes neither, and printing them as model
output invites an analyst to treat a guess as a finding.

What replaces it is a number the pipeline can defend line by line:

```
concern = 100 × ( 0.50 × negativity × confidence
                + 0.22 × toxicity
                + 0.18 × virality
                + 0.10 × term_severity )
```

- **Formula:** [`app/ml/score.py`](../backend/app/ml/score.py). `negativity` is
  `max(0, −sentiment_score)`, so a positive post contributes nothing to it.
- **Weights are shaped so no single dimension reaches an alert band alone:** a
  furious post nobody read tops out near 50, a viral cheerful post cannot pass
  ~30. An alert always means *negative **and** travelling*.
- **Bands:** ≥74 critical (+ auto escalation packet) · ≥65 high · ≥50 elevated.
- The per-factor contribution is stored on the post and rendered in the drawer
  under *How this score was built*, so an analyst can see that a 71 came from
  reach rather than from the language itself.
- The lexicon layer (`app/ml/classifier.py`) still extracts violence, hostility,
  abuse and mobilization **signals** — those are facts about the text, and they
  feed toxicity and `term_severity`. They assert nothing beyond themselves.

## 6. Independent verification (Groq LLM)

Every risky or consensus prediction is sent to **Groq `llama-3.3-70b`** for an
independent second opinion ([`app/services/groq_verifier.py`](../backend/app/services/groq_verifier.py)):

- **Agreement** with the ensemble strengthens confidence.
- **Confident disagreement** (LLM confidence ≥ 0.75) **overrides** the label and
  recomputes the score — never silently; the full LLM verdict, quoted evidence
  and reasoning are stored and shown.
- For the sentiment consensus, Groq's independent sentiment is recorded as
  `groq_sentiment` / `groq_agrees` on the post.

Suspected **fake news** is additionally checked against **Google News India**
for cross-source corroboration (`app/services/fact_check.py`), and an
analyst-grade **evidence dossier** (`app/services/evidence.py`) compiles quoted
evidence, claim-by-claim assessment and cited sources on demand.

---

## 7. Training data provenance

All models train on the same corpus assembled by `app/ml/corpus.py` from **22
public datasets** (Kaggle + HuggingFace) covering English, Hindi, Gujarati,
Hinglish and Gujlish social-media text, de-duplicated and per-language capped,
plus LLM-augmented examples for minority classes. **48,774 train / 5,768 test**
rows. See [`backend/app/data/datasets/README.md`](../backend/app/data/datasets/README.md)
for the per-source breakdown. Rebuild everything with `python -m app.ml.bootstrap`.
