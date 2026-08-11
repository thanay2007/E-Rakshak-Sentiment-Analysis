"""What SENTINEL is, written down so the assistant can explain it.

This is the half of "answer any question about the project" that no database
query reaches. "How is the threat score calculated?", "why is this in Gujlish
and English?", "what does amplified mean?", "who can escalate an alert?" are
all questions about the *system*, and the only honest way to answer them is
from the system's own documented behaviour.

Every entry below is copied from the code it describes — `ml/concern_score.py`
for the formula, `services/model_info.py` for the ensemble, `security/roles.py`
for the rank ladder, `models/models.py` for the vocabularies. When one of those
changes, this changes. An assistant confidently reciting a formula the product
stopped using is worse than one that says "I don't know", because the officer
has no way to tell the difference.

Retrieval is deliberately boring: IDF-weighted term overlap over a few dozen
short entries. No embedding model, no vector store, no network call, nothing
that can be unavailable at 3am. At this corpus size the ranking a real
retriever would give is the same one this gives.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.config import settings


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    body: str
    # Extra query terms that should hit this entry but do not appear in its
    # prose — spoken synonyms, abbreviations, and the words an officer would
    # actually use rather than the ones the code uses.
    tags: tuple[str, ...] = field(default=())


def _cities() -> str:
    return ", ".join(settings.TARGET_CITIES)


ENTRIES: list[Entry] = [
    Entry(
        "overview",
        "What SENTINEL is",
        f"SENTINEL is a social-media threat and sentiment monitoring system built "
        f"for Gujarat Police, mentored by NIC Rajkot. It continuously collects "
        f"public posts from the cities it monitors ({_cities()}), runs them "
        f"through a multilingual NLP pipeline, scores each one for threat, and "
        f"raises alerts on the ones that matter. Its purpose is to detect "
        f"coordinated hate campaigns and fake-news amplification early. It is a "
        f"monitoring and triage tool, not a fact-checker and not an arrest "
        f"system — every alert is a lead for a human officer to judge.",
        ("sentinel", "e-rakshak", "erakshak", "project", "what is this",
         "purpose", "goal", "about", "mission", "gujarat", "police", "nic"),
    ),
    Entry(
        "scope",
        "What the system deliberately does not do",
        "SENTINEL traces how content spreads; it does not decide whether a claim "
        "is true. It targets coordinated campaigns rather than individual "
        "criticism — an angry post from one ordinary account is not the target, "
        "fifty near-identical posts appearing within an hour are. It does not "
        "monitor private messages, only public posts from seed sources the "
        "deployment has configured. It does not take enforcement action.",
        ("limits", "cannot", "not do", "privacy", "ethics", "criticism",
         "censorship", "surveillance"),
    ),
    Entry(
        "cities",
        "Which cities are monitored",
        f"This deployment monitors {_cities()}. A post gets a location from the "
        f"seed source it came from (each configured page, subreddit or channel "
        f"carries a city tag) or from place names found in the text by the "
        f"geo-tagger. Posts with no resolvable city keep an empty location "
        f"rather than being guessed into one.",
        ("city", "cities", "surat", "ahmedabad", "vadodara", "baroda", "rajkot",
         "location", "geo", "where", "coverage", "area"),
    ),
    Entry(
        "sources",
        "Where the posts come from",
        "Collectors live in backend/app/crawlers: Reddit, Facebook, Instagram, "
        "YouTube, Telegram and X, plus a simulator used for demos and testing. "
        "The strategy is seed sources, not the open web — a fixed list of public "
        "pages, subreddits and channels per city, so coverage is explainable and "
        "the crawl stays inside what the platform terms allow. Where an official "
        "API is unavailable the adapter falls back to a keyless public mirror "
        "rather than scraping a logged-in session.",
        ("source", "sources", "crawler", "collector", "scrape", "scraping",
         "reddit", "facebook", "instagram", "youtube", "telegram", "twitter",
         "api", "platform", "where do posts come from", "data"),
    ),
    Entry(
        "politeness",
        "Why collection is slow on purpose",
        f"Every collector enforces a minimum gap between hits on the same "
        f"endpoint — {settings.CRAWL_MIN_INTERVAL_SECONDS} seconds by default, "
        f"longer for YouTube. Rapid repeated queries against one endpoint look "
        f"like abuse and get the source blocked, which costs far more coverage "
        f"than the delay does. The scheduler batches work and waits rather than "
        f"polling hard.",
        ("rate limit", "slow", "interval", "politeness", "blocked", "throttle",
         "how often", "frequency", "schedule", "crawl"),
    ),
    Entry(
        "pipeline",
        "What happens to a post after collection",
        "One post goes through: normalisation (unicode, slang expansion), "
        "language identification, translation to an English gloss for the "
        "analyst, sentiment analysis, threat classification, toxicity scoring, "
        "keyword and watchlist matching, geo-tagging, bot and coordination "
        "checks, then the composite concern score. If the score clears the alert "
        "threshold an alert is raised. Enrichment is batched, and the whole "
        "pipeline has one entry point so seeding, live ingestion and evaluation "
        "all take exactly the same path.",
        ("pipeline", "process", "enrich", "enrichment", "stages", "flow",
         "how does it work", "ingestion", "steps"),
    ),
    Entry(
        "concern_score",
        "How the concern score is calculated",
        "The concern score is 0 to 100, and it is a weighted formula rather than "
        "a model output, so it can be explained line by line in court. Fifty "
        "percent is how negative the post is, scaled by how confident the "
        "ensemble is — a positive post contributes nothing here. Twenty-two "
        "percent is toxicity, meaning hate and abuse intensity including "
        "code-mixed slurs. Eighteen percent is virality, a log-scaled blend of "
        "likes, shares, comments and views, with a bonus if the post is part of "
        "a detected amplification burst. Ten percent is the severity of the "
        "strongest watchlist or lexicon term matched. The four are summed, "
        "clamped to 0-1 and multiplied by 100. The weights are shaped so no "
        "single dimension can reach an alert band alone: a furious post nobody "
        "read tops out near fifty, and a viral cheerful post cannot pass thirty.",
        ("concern score", "threat score", "score", "scoring", "formula",
         "calculated", "how is the score", "weights", "0 to 100", "rating"),
    ),
    Entry(
        "thresholds",
        "What the score bands mean",
        f"At or above {settings.CRITICAL_THRESHOLD} a post raises a critical "
        f"alert and an escalation template is generated with it. At or above "
        f"{settings.ALERT_THRESHOLD} it raises a high alert. At or above 50 it "
        f"counts as elevated on the dashboard. An alert therefore always means "
        f"the post is both negative and travelling, which is the only "
        f"combination worth an analyst's time.",
        ("threshold", "thresholds", "critical", "high", "band", "bands",
         "cutoff", "when does an alert", "severity", "what counts as"),
    ),
    Entry(
        "sentiment_labels",
        "The three tags a post can get",
        "Every post is tagged as exactly one of: positive, negative or neutral. "
        "That is the only category this system assigns. It does not classify "
        "posts as incitement, propaganda or misinformation — whether a post "
        "will cause violence, or whether a claim in it is false, are "
        "investigative conclusions that no model can reach from one post's "
        "text, so the system does not pretend to. Alongside the tag a post "
        "carries a concern score from 0 to 100 and an intent — informational, "
        "opinion, call to action, or rumor — which describes the speech act "
        "rather than any prediction about consequences.",
        ("label", "labels", "tag", "category", "categories", "classification",
         "positive", "negative", "neutral", "intent", "rumor",
         "call to action", "incitement", "fake news"),
    ),
    Entry(
        "sentiment_ensemble",
        "How sentiment is decided",
        "Three models vote on every post. First, a MuRIL transformer — a "
        "12-layer BERT pre-trained on 17 Indian languages, fine-tuned here as a "
        "three-class sentiment head; it is the most accurate overall and much "
        "the best on native-script Gujarati. Second, a classical TF-IDF plus "
        "LinearSVC model over word and character n-grams; the character n-grams "
        "absorb Hinglish spelling variants like bahut, bhut and bohot. Third, a "
        "multilingual valence lexicon in the VADER style, extended to Hindi, "
        "Gujarati, Hinglish and Gujlish, which is zero-shot and fully "
        "explainable. If two or more agree the majority wins with a consensus "
        "bonus; if all three disagree the most confident one is taken. A Groq "
        "LLM then independently double-checks the winning label.",
        ("sentiment", "ensemble", "consensus", "vote", "voting", "muril",
         "model", "models", "bert", "transformer", "svc", "lexicon", "vader",
         "positive", "negative", "neutral", "accuracy", "how accurate"),
    ),
    Entry(
        "threat_model",
        "The threat classifier itself",
        "Threat classification uses the same MuRIL base fine-tuned on a curated "
        "four-category dataset, backed by a lexicon threat layer and by Groq "
        "verification. Live accuracy figures — overall, macro F1 and per-class — "
        "are read from the evaluation reports produced during training and "
        "shown on the Settings page, so the numbers on screen are measured, not "
        "typed in.",
        ("threat model", "classifier", "muril", "trained", "training",
         "fine-tuned", "f1", "accuracy", "evaluation", "dataset"),
    ),
    Entry(
        "nlp_mode",
        "Full mode versus lite mode",
        f"NLP_MODE selects the engine. Full mode runs the fine-tuned "
        f"transformers and is what this deployment uses (currently "
        f"{settings.NLP_MODE}). Lite mode uses only the lexicon classifier and "
        f"needs no model downloads and no GPU — it exists so the app starts on a "
        f"laptop with nothing pre-installed. Full mode falls back to lite per "
        f"call if a model fails to load, so a missing weight file degrades "
        f"quality rather than breaking ingestion.",
        ("nlp mode", "lite", "full", "gpu", "cpu", "offline", "fallback",
         "download", "weights"),
    ),
    Entry(
        "languages",
        "How mixed-language posts are handled",
        "Posts are tagged Gujarati, Hindi, Hinglish, English or Mixed, and "
        "code-mixed posts are flagged. Gujlish and Hinglish — Gujarati or Hindi "
        "written in Latin script — are first-class, because that is how people "
        "actually post. Everything is translated to an English gloss for the "
        "analyst, and crucially the translation happens *before* any filtering: "
        "nothing is ever dropped for being in the wrong language or script, "
        "because that would be an obvious route for someone to evade monitoring.",
        ("language", "languages", "gujarati", "hindi", "hinglish", "gujlish",
         "code-mixed", "code mixed", "translation", "translate", "script",
         "romanized", "multilingual"),
    ),
    Entry(
        "coordination",
        "Coordinated campaigns and amplification",
        "Posts that appear near-identical within a short window are grouped "
        "under a shared cluster id and flagged as amplified; an empty cluster id "
        "means the post looks organic. Amplification adds to the virality term "
        "of the threat score. There is also a bot score per account, built from "
        "signals like account age, follower ratio and posting cadence. This is "
        "the part that separates a coordinated campaign from fifty people "
        "independently being angry about the same thing.",
        ("coordinated", "coordination", "campaign", "cluster", "amplified",
         "amplification", "bot", "bots", "botnet", "burst", "organic",
         "inauthentic", "brigading"),
    ),
    Entry(
        "alerts",
        "How alerts work",
        "An alert is raised when a post clears the alert threshold. It carries a "
        "severity — critical, high or medium — and a status that moves from new "
        "to acknowledged to escalated as officers work it. Critical alerts "
        "arrive live over a websocket and can be read aloud as they land. "
        "Escalating an alert is a supervisor action and is recorded in the audit "
        "trail with the officer's name and badge.",
        ("alert", "alerts", "severity", "acknowledge", "escalate", "escalation",
         "status", "new", "notification", "websocket", "live"),
    ),
    Entry(
        "watchlist",
        "What the watchlist does",
        "The watchlist holds terms matched against every collected post: "
        "keywords, hashtags, accounts and locations, each with a priority from "
        "low to critical. A match feeds the keyword-severity term of the threat "
        "score, so adding a term genuinely changes what gets flagged rather than "
        "just filtering the view. Terms can be grouped into named preset packs.",
        ("watchlist", "watch list", "keyword", "keywords", "hashtag", "terms",
         "monitor", "tracking", "priority"),
    ),
    Entry(
        "investigate",
        "The investigation toolkit",
        "Investigate is the hands-on side of the product: reverse image "
        "analysis, URL and domain checks, username lookups across platforms, "
        "comment-thread analysis, audio and media intelligence, and a face "
        "search against the suspect registry. All of it is deliberately "
        "keyboard-only — the voice assistant will not run any of it, because "
        "these are the searches that name individuals.",
        ("investigate", "investigation", "osint", "toolkit", "image", "url",
         "username", "lookup", "reverse", "media", "tools"),
    ),
    Entry(
        "network",
        "The network graph",
        "The network view draws accounts as nodes and their shared content, "
        "mentions and cluster membership as edges. It is how a coordinated set "
        "gets seen as a set: a dense component of young accounts pushing one "
        "narrative looks nothing like organic conversation about the same topic.",
        ("network", "graph", "nodes", "edges", "connections", "accounts",
         "relationship", "visual"),
    ),
    Entry(
        "reports",
        "Reports and evidence",
        "Reports assemble an incident or escalation package for a chosen time "
        "window and render it to PDF. Evidence dossiers capture the post, its "
        "scores, the reasoning behind them and the chain of collection, so a "
        "finding can be handed to someone who was not watching the screen. "
        "Generating and exporting are hands-on actions, never voice ones.",
        ("report", "reports", "pdf", "evidence", "dossier", "export",
         "document", "package", "incident"),
    ),
    Entry(
        "fact_check",
        "The fact-check layer",
        "Where a post makes a checkable claim, a fact-check pass searches for "
        "corroborating coverage and records a verdict of corroborated, partially "
        "corroborated or uncorroborated, with the matches it found. This is "
        "context for the analyst, not a ruling — uncorroborated means nothing "
        "was found, not that the claim is false.",
        ("fact check", "fact-check", "verify", "verification", "true", "false",
         "misinformation", "corroborated", "claim"),
    ),
    Entry(
        "roles",
        "Who can do what",
        "Three ranks, strictly ordered. An analyst reads the feed, runs "
        "investigations and generates reports. A supervisor adds the "
        "irreversible calls — escalating alerts, bulk export, deleting registry "
        "records, triggering crawls. An admin adds user management, retention "
        "purges and the operations toolkit. Checks are always 'at least this "
        "rank', never an exact-match list, so adding a rank later cannot "
        "silently strip permissions from the ranks below it.",
        ("role", "roles", "permission", "permissions", "rbac", "analyst",
         "supervisor", "admin", "rank", "access", "who can", "allowed"),
    ),
    Entry(
        "security",
        "How the system protects itself",
        "Sessions are JWT-based with a token version that invalidates every "
        "existing token when an account changes, plus idle logout in the "
        "browser. Every consequential action is written to an audit trail with "
        "the actor's identity, IP and user agent. Requests are rate-limited per "
        "identity with a tighter budget for expensive operations. Outbound "
        "fetches go through an SSRF guard so a hostile URL cannot make the "
        "server probe its own network. Face templates and mugshots are "
        "encrypted at rest.",
        ("security", "secure", "auth", "authentication", "jwt", "token",
         "session", "audit", "rate limit", "ssrf", "encryption", "protect",
         "hardening"),
    ),
    Entry(
        "assistant_self",
        "What the assistant is and is not",
        "This assistant reads the live picture and explains how the system "
        "works. It is read-only by construction: there is no code path from a "
        "spoken word to anything that writes, so it cannot acknowledge an alert, "
        "change a watchlist, export a report or delete a row even if asked "
        "plainly. It refuses officer accounts, credentials, the audit trail and "
        "biometric or registry lookups regardless of rank, because a microphone "
        "cannot tell who is standing at the terminal. Post text it shows on "
        "screen is never treated as instructions.",
        ("assistant", "you", "yourself", "voice", "sentinel assistant",
         "what can you do", "capabilities", "read only", "refuse", "limits",
         "microphone", "listen"),
    ),
    Entry(
        "voice_privacy",
        "Voice privacy",
        "Speech recognition runs in the browser through the Web Speech API. In "
        "Chrome and Edge that means the audio is sent to the browser vendor's "
        "speech service — it is not processed on this machine. That is why "
        "always-on wake-word listening is opt-in, off by default, and stated in "
        "the interface rather than buried in a document. Turn it off for "
        "sensitive briefings.",
        ("privacy", "microphone", "recording", "wake word", "hey sentinel",
         "listening", "audio", "speech", "cloud", "local"),
    ),
    Entry(
        "llm_layer",
        "Where the LLM is used, and where it is not",
        "A Groq-hosted LLM provides the second opinion on risky predictions, "
        "translation, evidence phrasing and this assistant's wording. It runs "
        "through one shared client with a model fallback chain, so a drained "
        "rate limit on one model moves the request to a sibling rather than "
        "failing. It never assigns the threat score — that stays a documented "
        "formula — and it is never given the ability to write to the database.",
        ("llm", "groq", "ai", "gpt", "llama", "language model", "second "
         "opinion", "fallback", "why llm", "openai"),
    ),
    Entry(
        "stack",
        "The technology stack",
        "Backend is FastAPI with SQLModel over SQLAlchemy, Alembic owning the "
        "schema, and either SQLite for a zero-setup local run or Postgres for a "
        "shared durable deployment — chosen entirely by the database URL. NLP is "
        "PyTorch and Hugging Face Transformers with scikit-learn for the "
        "classical model. Frontend is React with Vite, TypeScript, Tailwind and "
        "Framer Motion, talking to the backend through one typed API client and "
        "a websocket for live alerts.",
        ("stack", "tech", "technology", "framework", "fastapi", "react",
         "python", "typescript", "database", "postgres", "sqlite", "alembic",
         "built with", "architecture"),
    ),
    Entry(
        "simulation",
        "Simulated data",
        "The simulator generates realistic posts so the whole product can be "
        "demonstrated without waiting on live collection, and so the classifiers "
        "can be measured against known ground truth. Simulated posts carry a "
        "true label that real ones do not. Simulation is a deployment setting: "
        "with it off, the safety checks that a real rollout requires — such as "
        "biometric encryption being configured — become mandatory rather than "
        "advisory.",
        ("simulation", "simulated", "demo", "fake data", "seed", "test data",
         "ground truth", "accuracy"),
    ),
]

_INDEX = {e.id: e for e in ENTRIES}

# ── retrieval ───────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-z0-9]+")

# Words that appear in almost every question and would otherwise dominate the
# overlap score. Kept short: IDF already handles most of this, and an
# over-eager stop list breaks phrases like "what is this".
_STOP = frozenset("""
a an and are as at be by can could do does for from get give had has have how
i if in into is it its me my of on or our so tell that the their then there
these they this to us was we were what when where which who why will with
would you your show
""".split())


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower())
            if len(w) > 1 and w not in _STOP]


def _document(entry: Entry) -> str:
    # Title and tags twice: a term in either is a much stronger signal of what
    # the entry is *about* than the same term buried in its prose.
    return " ".join([entry.title, entry.title, " ".join(entry.tags),
                     " ".join(entry.tags), entry.body])


_DOC_TERMS: dict[str, list[str]] = {e.id: _terms(_document(e)) for e in ENTRIES}
_DOC_SETS: dict[str, set[str]] = {k: set(v) for k, v in _DOC_TERMS.items()}

_IDF: dict[str, float] = {}
for _term_set in _DOC_SETS.values():
    for _t in _term_set:
        _IDF[_t] = _IDF.get(_t, 0.0) + 1.0
_N = len(ENTRIES)
_IDF = {t: math.log(1 + _N / df) for t, df in _IDF.items()}


def search(question: str, limit: int = 3, min_score: float = 1.0) -> list[Entry]:
    """Best-matching entries, most relevant first.

    `min_score` exists so that a question the knowledge base genuinely does not
    cover returns nothing rather than the least-bad entry. The agent needs to
    be able to tell the difference — "I don't have that" is a legitimate and
    useful answer, and dressing up an irrelevant paragraph as one is not.
    """
    query = _terms(question)
    if not query:
        return []

    scored: list[tuple[float, Entry]] = []
    for entry in ENTRIES:
        doc = _DOC_SETS[entry.id]
        score = sum(_IDF.get(t, 1.0) for t in set(query) if t in doc)
        # Multi-word phrase hits ("threat score", "wake word") are worth more
        # than the same two words landing in different sentences.
        for i in range(len(query) - 1):
            if f"{query[i]} {query[i + 1]}" in _document(entry).lower():
                score += 1.5
        if score >= min_score:
            scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _score, entry in scored[:limit]]


def get(entry_id: str) -> Entry | None:
    return _INDEX.get(entry_id)


def topics() -> list[dict]:
    """Every entry's id and title — used by the capabilities endpoint so the UI
    can show what the assistant actually knows about."""
    return [{"id": e.id, "title": e.title} for e in ENTRIES]
