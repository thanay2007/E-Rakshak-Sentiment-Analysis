# SENTINEL — Architecture Diagrams

All diagrams are written in [Mermaid](https://mermaid.js.org/) and render natively on GitHub.
Each `.mmd` source file in this folder is validated with the Mermaid renderer; the
"edit live" links open the same diagram in the Mermaid Live editor.

| Diagram | Source | Edit live |
|---|---|---|
| System architecture | [`system-architecture.mmd`](system-architecture.mmd) | [open](https://l.mermaid.ai/zKcOWa) |
| Ingestion sequence (tick → dashboard) | [`ingestion-sequence.mmd`](ingestion-sequence.mmd) | [open](https://l.mermaid.ai/9CxgcF) |
| ML training pipeline (`app.ml.bootstrap`) | [`ml-training-pipeline.mmd`](ml-training-pipeline.mmd) | [open](https://l.mermaid.ai/ZjaNDC) |
| Threat scoring & alert bands | [`threat-scoring.mmd`](threat-scoring.mmd) | [open](https://l.mermaid.ai/Gb8Kqe) |
| Frontend structure | [`frontend-structure.mmd`](frontend-structure.mmd) | [open](https://l.mermaid.ai/4p1cAj) |

---

## 1. System architecture

End-to-end flow: platform collectors → NLP pipeline → intelligence layer → storage → API → dashboard.

```mermaid
flowchart LR
    subgraph COLLECT["Collectors — APScheduler loop, per-API politeness gaps"]
        SIM["Simulated stream (default, zero-key)"]
        FB["Facebook Graph API"]
        IG["Instagram Graph API"]
        RD["Reddit OAuth API"]
        XA["X API v2"]
        YT["YouTube Data API v3"]
        RSS["Generic Web / RSS"]
    end

    subgraph NLP["NLP Pipeline — full (MuRIL) / lite (lexicon) engines"]
        NORM["Normalize: slang, transliteration,\nURL/mention stripping"]
        LID["Language ID\nen / hi / gu / hinglish / gujlish"]
        THREAT["Threat classifier (4-way)\nfine-tuned MuRIL"]
        SENT["Sentiment + intent\nfine-tuned MuRIL"]
        TOX["Toxicity + hate flags"]
        SCORE["Composite threat score 0–100"]
        VERIFY["Groq LLM verification\n(optional second opinion)"]
    end

    subgraph INTEL["Intelligence"]
        TREND["Trend + z-score spike detection"]
        NET["Network centrality (networkx)"]
        BOT["Bot-cluster / coordinated\namplification detection"]
        ALERT["Alerting + escalation packets"]
        REPORT["PDF report generation"]
        GEO["Per-city geo-tagging\nSurat · Ahmedabad · Vadodara · Rajkot"]
    end

    COLLECT --> NORM --> LID --> THREAT --> SENT --> TOX --> SCORE --> VERIFY
    VERIFY --> INTEL

    DB[("SQLite / Postgres\n(SQLModel)")]
    API["FastAPI\nREST + WebSocket /ws/live"]
    FE["React + Vite + TypeScript\nTailwind · GSAP · Recharts · d3-force"]

    INTEL --> DB
    NLP --> DB
    DB --> API --> FE
```

## 2. Ingestion sequence

What happens on every scheduler tick, from crawl to live UI push.

```mermaid
sequenceDiagram
    autonumber
    participant SCH as APScheduler (crawl_tick)
    participant CR as Platform crawler
    participant NLP as NLP pipeline
    participant GROQ as Groq verifier (optional)
    participant DB as SQLite / Postgres
    participant WS as WebSocket hub (/ws/live)
    participant UI as React dashboard

    SCH->>CR: tick (respects per-API politeness gap)
    CR->>CR: fetch posts from seed sources + watchlist
    CR->>NLP: raw posts (any language / script)
    NLP->>NLP: normalize → language ID → classify threat,\nsentiment, toxicity → composite score
    alt risky post and GROQ_API_KEY set
        NLP->>GROQ: batched JSON-mode second opinion
        GROQ-->>NLP: agree (boost confidence) or\noverride label + rescore
    end
    NLP->>DB: persist post + NLP breakdown
    DB->>DB: alert bands: score ≥74 critical (auto-escalate),\n≥65 high, ≥50 active threat
    DB->>WS: new post + fired alerts
    WS-->>UI: live push (reconnecting socket)
    UI->>UI: update feed, KPIs, map, network graph
```

## 3. ML training pipeline

Everything `python -m app.ml.bootstrap` does, including the Groq augmentation branch.

```mermaid
flowchart TD
    BOOT["python -m app.ml.bootstrap\n(the one command)"]

    BOOT --> DEPS["Install base + ML deps\n(CUDA torch if GPU present)"]
    DEPS --> DL["download_datasets.py\n22 raw public datasets → app/data/datasets/\nKaggle · Hugging Face · GitHub (~400 MB, zero keys)"]

    DL --> CORPUS["corpus.py — assemble corpus in memory\nreads raw CSV / parquet / CoNLL directly\n(no merged intermediates ever written)"]

    DL --> AUG{"GROQ_API_KEY set?"}
    AUG -- yes --> GROQAUG["groq_augment.py — LLM augmentation\ngujlish-pairs 3.7k · genz 2.4k · gujarati 2.3k\nhinglish 2.3k · hindi 1.9k · gujlish 1.5k\nlabels always come from real data"]
    AUG -- no --> ROM["romanize.py fallback\nmechanical Gujarati → Gujlish transliteration"]
    GROQAUG --> CORPUS
    ROM --> CORPUS

    CORPUS --> TSENT["train_sentiment.py\nfine-tune google/muril-base-cased\n50k rows · 5 languages"]
    CORPUS --> TTHREAT["train.py\nfine-tune MuRIL threat classifier\n4 categories, template corpus"]
    CORPUS --> TBASE["train_baseline.py\nTF-IDF + LinearSVC baseline"]

    TSENT --> ESENT["eval_sentiment.py\n5,768 REAL held-out rows\noverall acc 0.706 · macro-F1 0.703"]
    TTHREAT --> ETHREAT["evaluate.py\n151 held-out samples, disjoint slots"]
    TBASE --> ESENT

    ESENT --> MODELS["app/ml/models/\nsentiment-classifier · threat-classifier\n+ eval reports"]
    ETHREAT --> MODELS
```

## 4. Threat scoring & alert bands

The composite score formula (`0.40 severity + 0.25 toxicity + 0.20 virality + 0.15 keywords`) and the bands that fire alerts.

```mermaid
flowchart TD
    POST["Classified post"]

    POST --> A["0.40 × severity(label) × confidence\nIncitement 1.00 · Inflammatory 0.75\nFake News 0.65 · Neutral 0.05"]
    POST --> B["0.25 × toxicity\nhate / abuse intensity"]
    POST --> C["0.20 × virality\nlog10(1 + likes + 3·shares + 2·comments + views/50) / 4\n+0.15 if inside a detected burst"]
    POST --> D["0.15 × keyword_severity\nstrongest lexicon term matched"]

    A --> SUM["score = 100 × Σ weighted components"]
    B --> SUM
    C --> SUM
    D --> SUM

    SUM --> BAND{"score band"}
    BAND -- "≥ 74" --> CRIT["CRITICAL alert\n+ auto-generated escalation packet"]
    BAND -- "≥ 65" --> HIGH["HIGH alert"]
    BAND -- "≥ 50" --> ACTIVE["Active threat"]
    BAND -- "< 50" --> MON["Monitored only"]

    CRIT --> UI["Analyst UI: alerts page,\ntoasts, report generation"]
    HIGH --> UI
    ACTIVE --> UI
```

## 5. Frontend structure

How `frontend/src` is organized: typed services feed hooks, hooks feed pages, pages compose components.

```mermaid
flowchart LR
    subgraph SERVICES["services/"]
        APITS["api.ts\ntyped REST client for every endpoint"]
        WSTS["ws.ts\nreconnecting /ws/live socket"]
    end

    subgraph HOOKS["hooks/"]
        POLL["usePolling"]
        LIVE["useLive / useLiveAlerts / useLiveStatus"]
        GSAPH["useGsapReveal · useCountUp"]
    end

    subgraph PAGES["pages/ (React Router)"]
        LAND["/ Landing"]
        DASH["/app Dashboard"]
        FEED["/app/feed Threat Feed"]
        NETP["/app/network Network"]
        TRND["/app/trends Trends"]
        ALRT["/app/alerts Alerts"]
        REPT["/app/reports Reports"]
        WTCH["/app/watchlist Watchlist"]
        SETT["/app/settings Settings"]
    end

    subgraph COMPONENTS["components/"]
        LAY["Layout · Sidebar · TopBar"]
        CARDS["GlassCard · StatTile · FeedItemCard\nBadges · Skeletons · Sparkline"]
        VIZ["GujaratMap (SVG geo)\nNetworkGraph (d3-force canvas)"]
        FX["BackgroundFX · AlertToasts · DetailDrawer"]
    end

    APITS --> POLL --> PAGES
    WSTS --> LIVE --> PAGES
    PAGES --> COMPONENTS
    GSAPH --> COMPONENTS
```
