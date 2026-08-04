"""SENTINEL — the voice assistant's server side.

A microphone is an authentication bypass waiting to happen. It is live in a
room full of people, it hears whoever is loudest, and unlike a keyboard there
is no way to tell from the transcript whether the officer or a bystander spoke.
So the rule this module is built around is: **the voice channel can read a
narrow, fixed set of aggregates and nothing else, and it can never write.**

That is enforced structurally, not by asking an LLM to behave:

  1. Every answer comes from one of the handlers in `_INTENTS`. Each is a fixed
     query written here. There is no free-form query path, no SQL from the
     transcript, and no handler that mutates — acknowledging an alert, changing
     a watchlist, resetting a password and purging data are simply not
     reachable from this router at all.

  2. `_FORBIDDEN` is checked *before* intent matching, so "read the alerts and
     list the officers" refuses rather than answering the half it liked. The
     sensitive surfaces — user accounts, the audit trail, biometrics and the
     suspect registry — are refused by voice even for an admin, because rank
     does not tell you who is actually standing at the terminal.

  3. When the LLM phrases a fallback answer it is handed **aggregate counts
     only**. Crawled post text is authored by the accounts under investigation;
     feeding it to an instruction-following model that an officer then trusts
     is a prompt-injection channel with a police uniform on. The model also
     cannot cause anything to happen: `navigate` is only ever set by the
     deterministic layer, so the worst a poisoned answer can do is be wrong
     out loud.

Authentication, the router-wide rate limit and `password_not_expired` are
applied by main.py; this module adds its own tighter budget on top, because a
hot mic in a noisy control room produces traffic an analyst never would.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, col, func, select

from app.config import settings
from app.database import get_session
from app.ml.geo import _ALIASES as CITY_ALIASES
from app.models import Alert, Post, User, WatchlistItem
from app.security.deps import current_user
from app.security.ratelimit import rate_limit
from app.services.audit import log_action

log = logging.getLogger("sentinel.assistant")
router = APIRouter()

_assistant_rate_limit = rate_limit(settings.RATE_LIMIT_ASSISTANT, bucket="assistant")


# ── request / response ──────────────────────────────────────────────────────

class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    # The page the officer is on, so "what am I looking at" has an answer.
    # Advisory only — never used to widen what may be read.
    page: str = Field(default="", max_length=80)


class AskResponse(BaseModel):
    intent: str
    reply: str
    speech: str
    navigate: str | None = None
    data: dict = {}
    source: str = "rules"


# ── what the voice channel may never touch ──────────────────────────────────

# Matched against the normalised transcript before anything else, and matched
# on the *subject* rather than on a phrasing. "list the officers", "list all
# officers", "who are the officers again" and "officers?" are one question; a
# denylist built from verb-plus-noun phrasings catches the first and waves the
# rest through, which is the failure mode this whole file exists to avoid.
#
# So: naming a protected subject at all is a refusal, because no capability in
# `_INTENTS` needs any of these words to answer. Fail-closed costs an
# occasional over-refusal, and an over-refusal costs one sentence.
_FORBIDDEN: list[tuple[str, str]] = [
    (r"\b(password|passcode|credential|log ?in as|sign ?in as|my login)\b",
     "I can't help with credentials by voice. Use Admin Panel → Officers."),
    (r"\b(officers?|personnel|roster|user ?names?|users?|staff list)\b",
     "Officer accounts aren't available by voice — I can't tell who's actually "
     "at the microphone. They're in Admin Panel → Officers."),
    (r"\b(audit|chain of custody)\b",
     "The audit trail isn't readable by voice — it names who investigated whom. "
     "Open Admin Panel → Audit Trail."),
    (r"\b(face|facial|biometric|mugshot|fingerprint|suspects?|registry|"
     r"criminal record|dossier)\b",
     "Biometric and registry lookups are done in Investigate, with your hands "
     "on the keyboard. I won't run them by voice."),
    (r"\b(delete|purge|remove|drop|wipe|erase|clear|reset|revoke|disable)\b",
     "I'm read-only. Nothing I do can change or delete anything — that has to "
     "be done in the dashboard."),
    (r"\b(acknowledge|escalate|dismiss|resolve|assign|action)\b",
     "I can't action alerts by voice. I'll take you to the alert and you can "
     "action it there."),
    (r"\b(export|download|generate|email|send)\b",
     "Exports and sending are hands-on actions. I'll open Reports for you."),
    (r"\b(api ?key|secret|bearer|access token|environment variable|"
     r"database url|connection string|\.env)\b",
     "I don't disclose configuration."),
]

_FORBIDDEN_COMPILED = [(re.compile(p), msg) for p, msg in _FORBIDDEN]


# ── helpers ─────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalise(raw: str) -> str:
    """Fold a speech transcript into something matchable.

    NFKC first: dictation engines emit typographic punctuation and full-width
    forms that would otherwise break every pattern below. Control characters go
    entirely — they carry no speech and only serve to smuggle line breaks into
    the audit record.
    """
    text = unicodedata.normalize("NFKC", raw)
    text = "".join(ch for ch in text if ch == " " or not unicodedata.category(ch).startswith("C"))
    # Dictation engines emit typographic quotes, and NFKC does not fold them.
    # Every pattern below is written with a straight apostrophe, so "what's"
    # dictated as "what’s" would silently match nothing.
    text = text.translate(str.maketrans({"‘": "'", "’": "'",
                                         "“": '"', "”": '"',
                                         "–": "-", "—": "-"}))
    text = text.lower().strip()
    # The wake word is part of the utterance when the browser streams
    # continuously; strip it so "hey sentinel, show alerts" matches "show alerts".
    text = re.sub(r"^(hey|hi|ok|okay|hello)?\s*(sentinel|sentinal|sentinelle|centinel)\b[,\s]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _city_in(text: str) -> str:
    """Resolve a spoken city to its canonical name, or "" if none is named."""
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return city
    return ""


def _hours_in(text: str, default: int = 24) -> int:
    """Pull a window out of the utterance: "last 6 hours", "past week", "today"."""
    if re.search(r"\b(week|7 days|seven days)\b", text):
        return 168
    if re.search(r"\b(today|24 hours|day)\b", text):
        return 24
    m = re.search(r"\b(\d{1,6})\s*(hour|hr)s?\b", text)
    if m:
        # Clamped rather than rejected: "the last thousand hours" is a real way
        # of saying "everything you have", and the corpus only goes back a week.
        return max(1, min(int(m.group(1)), 168))
    return default


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


def _since(hours: int) -> datetime:
    return _utcnow() - timedelta(hours=hours)


def _snippet(text: str, limit: int = 140) -> str:
    """Truncate crawled text for display.

    Shown in the panel, never spoken and never sent to the LLM — see the module
    docstring on why post text is kept away from the model.
    """
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# ── intent handlers ─────────────────────────────────────────────────────────
#
# Each returns (speech, reply, navigate, data). `speech` is what gets read out —
# short, no punctuation soup, no URLs. `reply` is what the panel shows.

def _brief(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    hours = _hours_in(text)
    since = _since(hours)
    posts = session.exec(select(func.count()).select_from(Post)
                         .where(Post.created_at >= since)).one()
    threats = session.exec(select(func.count()).select_from(Post)
                           .where(Post.created_at >= since)
                           .where(Post.threat_score >= settings.ALERT_THRESHOLD)).one()
    new_alerts = session.exec(select(func.count()).select_from(Alert)
                              .where(Alert.created_at >= since)
                              .where(col(Alert.status) == "new")).one()
    critical = session.exec(select(func.count()).select_from(Alert)
                            .where(Alert.created_at >= since)
                            .where(col(Alert.severity) == "critical")).one()
    window = "the last 24 hours" if hours == 24 else f"the last {_plural(hours, 'hour')}"
    speech = (f"In {window} I've monitored {_plural(posts, 'post')}. "
              f"{_plural(threats, 'post')} scored above the alert threshold, "
              f"and there {'is' if new_alerts == 1 else 'are'} "
              f"{_plural(new_alerts, 'unactioned alert')}")
    speech += f", {_plural(critical, 'of them critical', 'of them critical')}." if critical else "."
    data = {"window_hours": hours, "posts": posts, "threats": threats,
            "new_alerts": new_alerts, "critical": critical}
    return speech, speech, None, data


def _alerts(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    hours = _hours_in(text, 24)
    since = _since(hours)
    only_critical = bool(re.search(r"\bcritical\b", text))

    stmt = select(Alert).where(Alert.created_at >= since)
    count_stmt = select(func.count()).select_from(Alert).where(Alert.created_at >= since)
    if only_critical:
        stmt = stmt.where(col(Alert.severity) == "critical")
        count_stmt = count_stmt.where(col(Alert.severity) == "critical")
    rows = session.exec(stmt.order_by(col(Alert.created_at).desc()).limit(5)).all()
    total = session.exec(count_stmt).one()

    kind = "critical alert" if only_critical else "alert"
    if not rows:
        speech = f"No {kind}s in the last {_plural(hours, 'hour')}."
        return speech, speech, "/app/alerts", {"count": 0, "items": []}

    lead = f"{_plural(total, kind)} in the last {_plural(hours, 'hour')}."
    spoken = [f"{a.severity}, {a.title}, in {a.location or 'an unspecified area'}, "
              f"scoring {round(a.threat_score)}" for a in rows[:3]]
    speech = lead + " " + ". ".join(spoken) + "."
    data = {"count": total, "items": [
        {"id": a.id, "severity": a.severity, "status": a.status, "title": a.title,
         "location": a.location, "platform": a.platform,
         "threat_score": round(a.threat_score, 1),
         "created_at": a.created_at.isoformat()} for a in rows]}
    return speech, lead, "/app/alerts", data


def _trends(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    hours = _hours_in(text)
    city = _city_in(text)
    since = _since(hours)

    stmt = select(Post).where(Post.created_at >= since)
    if city:
        stmt = stmt.where(col(Post.location) == city)
    posts = session.exec(stmt.order_by(col(Post.created_at).desc()).limit(4000)).all()

    tags: dict[str, int] = {}
    for p in posts:
        for tag in (p.hashtags or []):
            key = str(tag).lstrip("#").lower()
            if key:
                tags[key] = tags.get(key, 0) + 1
    top = sorted(tags.items(), key=lambda kv: kv[1], reverse=True)[:5]

    where = f"in {city}" if city else "across all monitored cities"
    if not top:
        speech = (f"Nothing is trending {where} in the last {_plural(hours, 'hour')}. "
                  f"I've opened the Trends page.")
        return speech, speech, "/app/trends", {"city": city, "window_hours": hours,
                                               "hashtags": []}

    named = ", ".join(f"{tag} with {_plural(n, 'mention')}" for tag, n in top[:3])
    speech = (f"Top trends {where} over the last {_plural(hours, 'hour')}: {named}. "
              f"Opening Trends.")
    reply = f"Top trends {where} — last {_plural(hours, 'hour')}."
    nav = "/app/trends" + (f"?city={city}" if city else "")
    data = {"city": city, "window_hours": hours, "posts_scanned": len(posts),
            "hashtags": [{"tag": t, "count": n} for t, n in top]}
    return speech, reply, nav, data


def _city_status(session: Session, text: str) -> tuple[str, str, str | None, dict] | None:
    city = _city_in(text)
    if not city:
        # Not a city question after all — "give me a situation report" trips the
        # same words. Decline so the loop keeps looking instead of answering
        # "which city?" to a question that never mentioned one.
        return None

    hours = _hours_in(text)
    since = _since(hours)
    base = select(func.count()).select_from(Post).where(
        Post.created_at >= since, col(Post.location) == city)
    posts = session.exec(base).one()
    threats = session.exec(
        base.where(Post.threat_score >= settings.ALERT_THRESHOLD)).one()
    avg = session.exec(
        select(func.avg(Post.threat_score)).where(
            Post.created_at >= since, col(Post.location) == city)).one() or 0
    alerts = session.exec(
        select(func.count()).select_from(Alert).where(
            Alert.created_at >= since, col(Alert.location) == city)).one()

    speech = (f"{city}, last {_plural(hours, 'hour')}: {_plural(posts, 'post')} "
              f"monitored, average threat score {round(float(avg))}, "
              f"{_plural(threats, 'post')} above threshold, "
              f"{_plural(alerts, 'alert')} raised.")
    data = {"city": city, "window_hours": hours, "posts": posts,
            "threats": threats, "avg_threat_score": round(float(avg), 1),
            "alerts": alerts}
    return speech, speech, f"/app/feed?location={city}", data


def _top_threat(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    hours = _hours_in(text)
    city = _city_in(text)
    stmt = select(Post).where(Post.created_at >= _since(hours))
    if city:
        stmt = stmt.where(col(Post.location) == city)
    post = session.exec(stmt.order_by(col(Post.threat_score).desc()).limit(1)).first()

    where = f" in {city}" if city else ""
    if post is None:
        speech = f"Nothing scored{where} in the last {_plural(hours, 'hour')}."
        return speech, speech, None, {}

    # The score, label, platform and account are spoken. The post's own words
    # are shown on screen but never read out — they are the suspect's words,
    # not the system's, and the distinction should not be lost in audio.
    speech = (f"Highest threat{where} is {round(post.threat_score)} out of 100, "
              f"labelled {post.threat_label}, from {post.author_handle or 'an unknown account'} "
              f"on {post.platform}. It's on screen.")
    data = {"post_id": post.id, "platform": post.platform,
            "author_handle": post.author_handle,
            "threat_label": post.threat_label,
            "threat_score": round(post.threat_score, 1),
            "sentiment_label": post.sentiment_label,
            "language": post.language, "location": post.location,
            "text": _snippet(post.translation or post.text),
            "created_at": post.created_at.isoformat()}
    return speech, speech, f"/app/feed?q={post.id}", data


def _platforms(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    hours = _hours_in(text)
    rows = session.exec(
        select(Post.platform, func.count()).where(Post.created_at >= _since(hours))
        .group_by(col(Post.platform))).all()
    counts = sorted(((str(p), int(n)) for p, n in rows), key=lambda kv: -kv[1])
    if not counts:
        speech = f"No platform activity in the last {_plural(hours, 'hour')}."
        return speech, speech, None, {"platforms": []}
    named = ", ".join(f"{p}, {_plural(n, 'post')}" for p, n in counts[:5])
    speech = f"Platform activity over the last {_plural(hours, 'hour')}: {named}."
    return speech, speech, None, {"platforms": [{"platform": p, "posts": n}
                                                for p, n in counts]}


def _watchlist(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    total = session.exec(select(func.count()).select_from(WatchlistItem)
                         .where(col(WatchlistItem.active) == True)).one()  # noqa: E712
    speech = (f"{_plural(total, 'active watchlist term')} are being matched "
              f"against every collected post. Opening the Watchlist.")
    return speech, speech, "/app/watchlist", {"active_terms": total}


_PAGES = {
    "overview": "/app", "dashboard": "/app", "home": "/app",
    "feed": "/app/feed", "threat feed": "/app/feed", "posts": "/app/feed",
    "investigate": "/app/investigate", "investigation": "/app/investigate",
    "network": "/app/network", "graph": "/app/network",
    "trends": "/app/trends", "trend": "/app/trends",
    "alerts": "/app/alerts", "alert": "/app/alerts",
    "reports": "/app/reports", "report": "/app/reports",
    "watchlist": "/app/watchlist",
    "settings": "/app/settings",
    "admin": "/app/admin", "admin panel": "/app/admin",
}


def _navigate(session: Session, text: str) -> tuple[str, str, str | None, dict] | None:
    # Longest label first so "threat feed" wins over "feed".
    for label in sorted(_PAGES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(label)}\b", text):
            speech = f"Opening {label}."
            return speech, speech, _PAGES[label], {"page": label}
    # A navigation verb with no page named — "open up the last 24 hours" — is
    # someone asking for content, not a destination. Decline and let a content
    # intent take it.
    return None


def _help(session: Session, text: str) -> tuple[str, str, str | None, dict]:
    speech = ("I can brief you on the last 24 hours, read out alerts, give you "
              "trends for a city, name the highest-scoring post, break activity "
              "down by platform, and open any page. I'm read-only — I can't "
              "change, action or delete anything.")
    return speech, speech, None, {"examples": _EXAMPLES}


_EXAMPLES = [
    "Hey Sentinel, brief me",
    "Hey Sentinel, tell me the trends in Surat",
    "Hey Sentinel, any critical alerts?",
    "Hey Sentinel, what's the highest threat post today?",
    "Hey Sentinel, how is Ahmedabad looking this week?",
    "Hey Sentinel, open the threat feed",
]

# Order matters: the first pattern that matches *and whose handler accepts*
# wins. A handler returning None means "those words matched but this isn't my
# question", which is what lets a bare navigation verb or a city-less status
# query fall through to something that can actually answer it.
#
# Explicit navigation sits first on purpose. "Take me to trends" is a request
# for a destination; "show me the trends" is a request for content, and only
# the first list of verbs below is unambiguous about which.
_INTENTS: list[tuple[str, re.Pattern, object]] = [
    ("navigate", re.compile(r"\b(open|go to|take me to|navigate to|switch to|"
                            r"jump to|bring up)\b"), _navigate),
    ("help", re.compile(r"\b(help|what can you do|commands|how do you work)\b"), _help),
    ("alerts", re.compile(r"\balerts?\b|\bescalations?\b"), _alerts),
    ("top_threat", re.compile(
        r"\b(highest|top|worst|most (severe|dangerous|serious)|biggest)\b.*"
        r"\b(threat|post|score|risk)\b|\bworst post\b"), _top_threat),
    ("trends", re.compile(r"\btrend(s|ing)?\b|\bhashtags?\b|\bwhat'?s (hot|spreading)\b"), _trends),
    ("platforms", re.compile(r"\bplatforms?\b|\bby (source|platform)\b|"
                             r"\b(twitter|reddit|telegram|instagram|facebook|youtube)\b"), _platforms),
    ("watchlist", re.compile(r"\bwatch ?list\b|\bkeywords? (we|being) (watch|monitor)"), _watchlist),
    ("city_status", re.compile(
        r"\b(status|situation|how is|how'?s|what'?s happening|update on|report on|"
        r"looking|doing)\b"), _city_status),
    ("brief", re.compile(r"\b(brief|briefing|summary|summarise|summarize|overview|"
                         r"sit ?rep|situation report|what'?s going on|catch me up)\b"), _brief),
]


# ── endpoint ────────────────────────────────────────────────────────────────

@router.get("/assistant/capabilities")
def capabilities(user: User = Depends(current_user)) -> dict:
    """What Sentinel will answer — published so the UI never advertises more
    than the server actually allows, and so the limits are inspectable."""
    return {
        "enabled": settings.ASSISTANT_ENABLED,
        "name": "Sentinel",
        "wake_words": ["hey sentinel", "sentinel"],
        "read_only": True,
        "capabilities": [
            {"intent": "brief", "description": "Situation summary for a time window"},
            {"intent": "alerts", "description": "Recent and critical alerts"},
            {"intent": "trends", "description": "Trending hashtags, optionally per city"},
            {"intent": "city_status", "description": "Post volume and threat level for a city"},
            {"intent": "top_threat", "description": "Highest-scoring post in a window"},
            {"intent": "platforms", "description": "Activity broken down by platform"},
            {"intent": "watchlist", "description": "How many terms are being matched"},
            {"intent": "navigate", "description": "Open any dashboard page"},
        ],
        "refuses": [
            "officer accounts and credentials",
            "the audit trail",
            "biometric and suspect-registry lookups",
            "any action that changes, actions, exports or deletes data",
            "configuration and secrets",
        ],
        "cities": settings.TARGET_CITIES,
        "examples": _EXAMPLES,
    }


@router.post("/assistant/ask", response_model=AskResponse,
             dependencies=[Depends(_assistant_rate_limit)])
async def ask(body: AskRequest, session: Session = Depends(get_session),
              user: User = Depends(current_user)) -> AskResponse:
    if not settings.ASSISTANT_ENABLED:
        raise HTTPException(503, "The voice assistant is disabled on this instance.")

    # Truncate rather than reject: a dictation engine that ran on will produce a
    # long transcript with a perfectly good question at the front of it.
    text = _normalise(body.query)[: settings.ASSISTANT_MAX_QUERY_CHARS]
    if not text:
        speech = "I didn't catch that."
        return AskResponse(intent="empty", reply=speech, speech=speech)

    # Refusals come first, and are audited — a voice request for the officer
    # roster is exactly the event a reviewer would want to find later.
    for pattern, message in _FORBIDDEN_COMPILED:
        if pattern.search(text):
            log_action(session, "assistant_refused", "",
                       {"query": text[:200], "reason": pattern.pattern[:80]})
            return AskResponse(intent="refused", reply=message, speech=message,
                               source="refusal")

    for name, pattern, handler in _INTENTS:
        if not pattern.search(text):
            continue
        result = handler(session, text)  # type: ignore[operator]
        if result is None:
            continue          # matched the words, not the question — keep looking
        speech, reply, navigate, data = result
        log_action(session, "assistant_query", "",
                   {"query": text[:200], "intent": name})
        return AskResponse(intent=name, reply=reply, speech=speech,
                           navigate=navigate, data=data)

    return await _fallback(session, text, body.page)


async def _fallback(session: Session, text: str, page: str) -> AskResponse:
    """Nothing matched. Phrase something useful from aggregates, or say so.

    The LLM sees numbers this function computed and the officer's question. It
    does not see post text, it is not given tools, and its answer is never
    parsed for actions — `navigate` stays None on this path by construction.
    """
    fallback = ("I'm not sure about that one. I can brief you on the last 24 "
                "hours, read out alerts, give you trends for a city, or open "
                "any page. Ask me for help to hear the full list.")

    if not settings.ASSISTANT_LLM_FALLBACK:
        return AskResponse(intent="unknown", reply=fallback, speech=fallback)

    from app.services import groq_client
    if not groq_client.enabled():
        return AskResponse(intent="unknown", reply=fallback, speech=fallback)

    since = _since(24)
    snapshot = {
        "posts_last_24h": session.exec(
            select(func.count()).select_from(Post).where(Post.created_at >= since)).one(),
        "posts_above_alert_threshold": session.exec(
            select(func.count()).select_from(Post).where(
                Post.created_at >= since,
                Post.threat_score >= settings.ALERT_THRESHOLD)).one(),
        "open_alerts": session.exec(
            select(func.count()).select_from(Alert).where(
                col(Alert.status) == "new")).one(),
        "critical_alerts_24h": session.exec(
            select(func.count()).select_from(Alert).where(
                Alert.created_at >= since, col(Alert.severity) == "critical")).one(),
        "cities_monitored": settings.TARGET_CITIES,
        "current_page": page[:40],
    }

    system = (
        "You are Sentinel, the voice assistant inside an Indian police OSINT "
        "dashboard. Answer in at most two spoken sentences, plainly, no "
        "markdown, no lists, no URLs. You may use only the JSON figures given. "
        "If the question needs anything not in them, say you can't answer that "
        "and name one thing you can do: brief the last 24 hours, read alerts, "
        "give city trends, or open a page. Never claim to have taken an action "
        "— you are read-only."
    )
    try:
        # json_mode=False — the client defaults to asking for a JSON object, and
        # this answer is spoken aloud. A little temperature keeps the phrasing
        # from sounding like a form letter on repeat questions.
        content, _model = await groq_client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": f"Figures: {snapshot}\n\nQuestion: {text}"}],
            json_mode=False, temperature=0.3)
    except Exception:
        log.exception("assistant llm fallback failed")
        content = None

    if not content:
        return AskResponse(intent="unknown", reply=fallback, speech=fallback)

    # Trim hard: this gets read aloud, and a model that ignored the length
    # instruction should not hold the room for a paragraph.
    spoken = re.sub(r"\s+", " ", content).strip()[:400]
    log_action(session, "assistant_query", "", {"query": text[:200], "intent": "llm"})
    return AskResponse(intent="llm", reply=spoken, speech=spoken, source="llm")
