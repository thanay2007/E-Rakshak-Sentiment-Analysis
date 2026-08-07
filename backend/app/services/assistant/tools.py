"""Everything the assistant is able to do, and nothing else.

The model does not have access to the database. It has access to this list.
Each entry is a hand-written query with a fixed shape, a declared minimum rank,
and a JSON schema the model fills in — so the surface an officer's microphone
exposes is exactly the surface written down here, reviewable in one file.

Three properties hold across the whole registry, and they are what make it
safe to let a language model drive:

  **Nothing writes.** There is no handler that mutates, and no import in this
  module that could. Acknowledging an alert, changing a watchlist, purging
  data and resetting a password are not "blocked" — they are absent.

  **Rank gates the list, not the answer.** `for_role()` filters the tool list
  before it is shown to the model, and `invoke()` re-checks on the way in. A
  model cannot be talked into calling a tool it was never told exists, and it
  cannot call one it was told about by another route either.

  **Crawled text is sanitised at the boundary.** The handful of tools that
  return post or alert wording pass it through `guard.sanitise_untrusted`
  before it leaves the handler, so no invisible character, newline or fence
  delimiter authored by a monitored account ever reaches the model's context
  intact. The agent then fences the whole payload again.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlmodel import Session, col, func, select

from app.config import settings
from app.ml.geo import _ALIASES as CITY_ALIASES
from app.models import Alert, Post, User, WatchlistItem
from app.security.roles import ADMIN, ANALYST, SUPERVISOR, at_least  # noqa: F401
from app.services.assistant import guard, knowledge, sandbox

log = logging.getLogger("sentinel.assistant.tools")

# How many posts a Python-side aggregation will pull before giving up on being
# exact. Hashtag counting and time bucketing cannot be expressed portably
# across SQLite and Postgres, so they happen here — bounded, and the bound is
# reported back so an answer built on a partial scan says so.
SCAN_LIMIT = 6000


# ── shared parsing helpers (also used by the deterministic rules layer) ─────

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def since(hours: int) -> datetime:
    return utcnow() - timedelta(hours=hours)


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many or one + 's'}"


def city_in(text: str) -> str:
    """Resolve a spoken city to its canonical name, or "" if none is named."""
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return city
    return ""


def hours_in(text: str, default: int = 24) -> int:
    """Pull a window out of an utterance: "last 6 hours", "past week", "today"."""
    if re.search(r"\b(month|30 days|thirty days)\b", text):
        return 720
    if re.search(r"\b(week|7 days|seven days)\b", text):
        return 168
    if re.search(r"\b(today|24 hours|day)\b", text):
        return 24
    m = re.search(r"\b(\d{1,6})\s*(hour|hr)s?\b", text)
    if m:
        # Clamped rather than rejected: "the last thousand hours" is a real way
        # of saying "everything you have".
        return max(1, min(int(m.group(1)), 720))
    m = re.search(r"\b(\d{1,3})\s*days?\b", text)
    if m:
        return max(1, min(int(m.group(1)) * 24, 720))
    return default


def _clamp_hours(value: Any, default: int = 24) -> int:
    try:
        return max(1, min(int(value), 720))
    except (TypeError, ValueError):
        return default


def _clamp_limit(value: Any, default: int = 5, ceiling: int = 20) -> int:
    try:
        return max(1, min(int(value), ceiling))
    except (TypeError, ValueError):
        return default


def _canonical_city(value: Any) -> str:
    """Map whatever the model said to a city this deployment actually knows.

    Returns "" for anything unrecognised rather than passing it into a query,
    so an invented city name yields "no filter" instead of a silent zero.
    """
    if not value:
        return ""
    text = str(value).strip().lower()
    for city, aliases in CITY_ALIASES.items():
        if text == city.lower() or text in aliases:
            return city
    return ""


# ── the shape a handler returns ─────────────────────────────────────────────

@dataclass
class ToolResult:
    # Goes to the model. Must be small, JSON-safe and free of raw crawled text.
    payload: dict
    # Extra detail for the on-screen panel only — never sent to the model, so
    # it can be richer than what the model is trusted to summarise.
    display: dict = field(default_factory=dict)
    # In-app path to open. Set only by `navigate`, never inferred from prose.
    navigate: str | None = None


@dataclass
class ToolContext:
    session: Session
    user: User
    page: str = ""


Handler = Callable[[ToolContext, dict], ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Handler
    min_role: str = ANALYST

    def schema(self) -> dict:
        """OpenAI/Groq function-calling shape."""
        return {"type": "function",
                "function": {"name": self.name,
                             "description": self.description,
                             "parameters": self.parameters}}


def _params(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


# Reused parameter fragments, so every tool describes a window and a city the
# same way and the model does not have to learn three conventions.
_HOURS = {"type": "integer",
          "description": "Look-back window in hours (1-720). Default 24."}
_CITY = {"type": "string",
         "description": f"Optional city filter. One of: "
                        f"{', '.join(settings.TARGET_CITIES)}. Omit for all."}
_PLATFORM = {"type": "string",
             "description": "Optional platform filter, e.g. Reddit, X, "
                            "Facebook, Instagram, Telegram, YouTube."}
_SENTIMENT = {"type": "string", "enum": ["positive", "neutral", "negative"],
              "description": "Optional sentiment filter."}


# ── query building ──────────────────────────────────────────────────────────

def _filtered_posts(args: dict):
    """A Post select with the standard filter set applied.

    Every filter is applied through a bound comparison on a real column — the
    argument value never becomes SQL. An unrecognised city or sentiment
    silently drops the filter rather than matching nothing, because "no posts
    in Mumbai" is a misleading answer to a question about a city this
    deployment does not monitor.
    """
    hours = _clamp_hours(args.get("hours"))
    stmt = select(Post).where(Post.created_at >= since(hours))

    city = _canonical_city(args.get("city"))
    if city:
        stmt = stmt.where(col(Post.location) == city)

    platform = str(args.get("platform") or "").strip()
    if platform:
        stmt = stmt.where(func.lower(col(Post.platform)) == platform.lower())

    sentiment = str(args.get("sentiment") or "").strip().lower()
    if sentiment in ("positive", "neutral", "negative"):
        stmt = stmt.where(col(Post.sentiment_label) == sentiment)

    language = str(args.get("language") or "").strip()
    if language:
        stmt = stmt.where(func.lower(col(Post.language)) == language.lower())

    label = str(args.get("threat_label") or "").strip()
    if label:
        stmt = stmt.where(func.lower(col(Post.threat_label)) == label.lower())

    if args.get("min_threat_score") is not None:
        try:
            stmt = stmt.where(Post.threat_score >= float(args["min_threat_score"]))
        except (TypeError, ValueError):
            pass

    if args.get("amplified_only"):
        stmt = stmt.where(col(Post.is_amplified) == True)  # noqa: E712

    return stmt, hours, city


def _count(session: Session, stmt) -> int:
    """Count the rows a filtered select would return, without fetching them."""
    return session.exec(select(func.count()).select_from(stmt.subquery())).one()


# ── handlers ────────────────────────────────────────────────────────────────

def _h_situation_brief(ctx: ToolContext, args: dict) -> ToolResult:
    hours = _clamp_hours(args.get("hours"))
    start = since(hours)
    s = ctx.session

    posts = s.exec(select(func.count()).select_from(Post)
                   .where(Post.created_at >= start)).one()
    above = s.exec(select(func.count()).select_from(Post)
                   .where(Post.created_at >= start)
                   .where(Post.threat_score >= settings.ALERT_THRESHOLD)).one()
    critical = s.exec(select(func.count()).select_from(Alert)
                      .where(Alert.created_at >= start)
                      .where(col(Alert.severity) == "critical")).one()
    unactioned = s.exec(select(func.count()).select_from(Alert)
                        .where(col(Alert.status) == "new")).one()
    avg = s.exec(select(func.avg(Post.threat_score))
                 .where(Post.created_at >= start)).one() or 0
    amplified = s.exec(select(func.count()).select_from(Post)
                       .where(Post.created_at >= start)
                       .where(col(Post.is_amplified) == True)).one()  # noqa: E712

    return ToolResult({
        "window_hours": hours,
        "posts_collected": posts,
        "posts_above_alert_threshold": above,
        "alert_threshold": settings.ALERT_THRESHOLD,
        "critical_alerts_in_window": critical,
        "unactioned_alerts_total": unactioned,
        "average_threat_score": round(float(avg), 1),
        "amplified_posts": amplified,
    })


def _h_count_posts(ctx: ToolContext, args: dict) -> ToolResult:
    stmt, hours, city = _filtered_posts(args)
    total = _count(ctx.session, stmt)
    # Averaged over the subquery's own column, not Post's. Naming `Post` here
    # re-introduces the base table into the FROM clause and silently averages
    # across a cartesian product of every post against every filtered post.
    sub = stmt.subquery()
    avg = ctx.session.exec(
        select(func.avg(sub.c.threat_score)).select_from(sub)).one() or 0
    return ToolResult({
        "matching_posts": total,
        "average_threat_score": round(float(avg), 1),
        "window_hours": hours,
        "filters_applied": {k: v for k, v in args.items() if v not in (None, "")},
        "city_resolved_to": city or "all monitored cities",
    })


_DIMENSIONS = {
    "platform": Post.platform,
    "city": Post.location,
    "location": Post.location,
    "language": Post.language,
    "sentiment": Post.sentiment_label,
    "threat_label": Post.threat_label,
    "intent": Post.intent,
}


def _h_breakdown(ctx: ToolContext, args: dict) -> ToolResult:
    dimension = str(args.get("dimension") or "platform").lower()
    column = _DIMENSIONS.get(dimension)
    if column is None:
        return ToolResult({"error": f"'{dimension}' is not a groupable dimension.",
                           "available": sorted(set(_DIMENSIONS))})

    stmt, hours, city = _filtered_posts(args)
    sub = stmt.subquery()
    grouped = ctx.session.exec(
        select(sub.c[column.key], func.count(), func.avg(sub.c.threat_score))
        .group_by(sub.c[column.key])).all()

    rows = sorted(
        ({"value": str(value or "unspecified"), "posts": int(n),
          "average_threat_score": round(float(avg or 0), 1)}
         for value, n, avg in grouped),
        key=lambda r: -r["posts"])[: _clamp_limit(args.get("limit"), 8, 20)]

    return ToolResult({"dimension": dimension, "window_hours": hours,
                       "city": city or "all", "groups": rows})


def _h_timeseries(ctx: ToolContext, args: dict) -> ToolResult:
    """Post volume and mean threat score over time.

    Bucketed in Python rather than SQL: date truncation has no portable
    spelling across SQLite and Postgres, and this runs on both.
    """
    stmt, hours, city = _filtered_posts(args)
    bucket_hours = 24 if hours > 72 else 1
    rows = ctx.session.exec(
        stmt.with_only_columns(col(Post.created_at), col(Post.threat_score))
        .order_by(col(Post.created_at).desc()).limit(SCAN_LIMIT)).all()

    buckets: dict[str, list[float]] = {}
    for created_at, score in rows:
        key = (created_at.strftime("%Y-%m-%d") if bucket_hours == 24
               else created_at.strftime("%Y-%m-%d %H:00"))
        buckets.setdefault(key, []).append(float(score or 0))

    series = [{"bucket": key, "posts": len(scores),
               "average_threat_score": round(sum(scores) / len(scores), 1)}
              for key, scores in sorted(buckets.items())]

    return ToolResult({"window_hours": hours, "city": city or "all",
                       "bucket": "day" if bucket_hours == 24 else "hour",
                       "scanned": len(rows), "partial_scan": len(rows) >= SCAN_LIMIT,
                       "series": series[-30:]})


def _h_trending_hashtags(ctx: ToolContext, args: dict) -> ToolResult:
    stmt, hours, city = _filtered_posts(args)
    posts = ctx.session.exec(
        stmt.order_by(col(Post.created_at).desc()).limit(SCAN_LIMIT)).all()

    counts: dict[str, int] = {}
    for post in posts:
        for tag in (post.hashtags or []):
            # Hashtags are authored by the accounts under investigation, so
            # they get the same sanitising as post text before being counted.
            key = guard.sanitise_untrusted(str(tag).lstrip("#").lower(), 40)
            if key:
                counts[key] = counts.get(key, 0) + 1

    top = sorted(counts.items(), key=lambda kv: -kv[1])[
        : _clamp_limit(args.get("limit"), 5, 20)]
    return ToolResult({"window_hours": hours, "city": city or "all",
                       "posts_scanned": len(posts),
                       "partial_scan": len(posts) >= SCAN_LIMIT,
                       "hashtags": [{"tag": tag, "mentions": n} for tag, n in top]})


def _h_top_posts(ctx: ToolContext, args: dict) -> ToolResult:
    stmt, hours, city = _filtered_posts(args)
    order = str(args.get("order_by") or "threat_score").lower()
    column = col(Post.created_at) if order == "recent" else col(Post.threat_score)
    limit = _clamp_limit(args.get("limit"), 3, 10)
    posts = ctx.session.exec(stmt.order_by(column.desc()).limit(limit)).all()

    def _row(post: Post, include_text: bool) -> dict:
        row = {
            "post_id": post.id,
            "platform": post.platform,
            "author_handle": guard.sanitise_untrusted(post.author_handle, 40),
            "author_followers": post.author_followers,
            "author_verified": post.author_verified,
            "threat_label": post.threat_label,
            "threat_score": round(post.threat_score, 1),
            "sentiment_label": post.sentiment_label,
            "intent": post.intent,
            "language": post.language,
            "location": post.location or "unspecified",
            "is_amplified": post.is_amplified,
            "coordinated": bool(post.cluster_id),
            "created_at": post.created_at.isoformat(),
        }
        if include_text:
            row["text_excerpt"] = guard.sanitise_untrusted(
                post.translation or post.text)
        return row

    # The model gets the scores and the metadata; the panel gets the wording.
    # A post's own words are the suspect's words, and they belong on screen in
    # front of an officer rather than paraphrased by a model or read aloud.
    return ToolResult(
        payload={"window_hours": hours, "city": city or "all",
                 "ordered_by": "most recent" if order == "recent" else "threat score",
                 "posts": [_row(p, include_text=False) for p in posts]},
        display={"posts": [_row(p, include_text=True) for p in posts]})


def _h_list_alerts(ctx: ToolContext, args: dict) -> ToolResult:
    hours = _clamp_hours(args.get("hours"))
    stmt = select(Alert).where(Alert.created_at >= since(hours))

    severity = str(args.get("severity") or "").strip().lower()
    if severity in ("critical", "high", "medium"):
        stmt = stmt.where(col(Alert.severity) == severity)
    status = str(args.get("status") or "").strip().lower()
    if status in ("new", "acknowledged", "escalated"):
        stmt = stmt.where(col(Alert.status) == status)
    city = _canonical_city(args.get("city"))
    if city:
        stmt = stmt.where(col(Alert.location) == city)

    total = _count(ctx.session, stmt)
    limit = _clamp_limit(args.get("limit"), 5, 15)
    rows = ctx.session.exec(
        stmt.order_by(col(Alert.created_at).desc()).limit(limit)).all()

    items = [{"alert_id": a.id, "severity": a.severity, "status": a.status,
              "title": guard.sanitise_untrusted(a.title, 120),
              "category": a.category, "location": a.location or "unspecified",
              "platform": a.platform, "threat_score": round(a.threat_score, 1),
              "created_at": a.created_at.isoformat()} for a in rows]

    return ToolResult({"window_hours": hours, "matching_alerts": total,
                       "city": city or "all", "showing": len(items),
                       "alerts": items})


def _h_city_comparison(ctx: ToolContext, args: dict) -> ToolResult:
    hours = _clamp_hours(args.get("hours"))
    start = since(hours)
    rows = []
    for city in settings.TARGET_CITIES:
        posts = ctx.session.exec(
            select(func.count()).select_from(Post)
            .where(Post.created_at >= start, col(Post.location) == city)).one()
        avg = ctx.session.exec(
            select(func.avg(Post.threat_score))
            .where(Post.created_at >= start, col(Post.location) == city)).one() or 0
        above = ctx.session.exec(
            select(func.count()).select_from(Post)
            .where(Post.created_at >= start, col(Post.location) == city,
                   Post.threat_score >= settings.ALERT_THRESHOLD)).one()
        alerts = ctx.session.exec(
            select(func.count()).select_from(Alert)
            .where(Alert.created_at >= start, col(Alert.location) == city)).one()
        rows.append({"city": city, "posts": posts,
                     "average_threat_score": round(float(avg), 1),
                     "posts_above_threshold": above, "alerts": alerts})

    rows.sort(key=lambda r: -r["average_threat_score"])
    return ToolResult({"window_hours": hours, "cities": rows,
                       "alert_threshold": settings.ALERT_THRESHOLD})


def _h_coordination(ctx: ToolContext, args: dict) -> ToolResult:
    """Coordinated-burst picture: how much of the window is inauthentic."""
    stmt, hours, city = _filtered_posts(args)
    sub = stmt.subquery()
    total = ctx.session.exec(select(func.count()).select_from(sub)).one()
    amplified = ctx.session.exec(
        select(func.count()).select_from(sub)
        .where(sub.c.is_amplified == True)).one()  # noqa: E712

    clusters = ctx.session.exec(
        select(sub.c.cluster_id, func.count())
        .where(sub.c.cluster_id != "")
        .group_by(sub.c.cluster_id)).all()
    ranked = sorted(((str(cid), int(n)) for cid, n in clusters),
                    key=lambda kv: -kv[1])[:5]

    return ToolResult({
        "window_hours": hours, "city": city or "all",
        "posts": total, "amplified_posts": amplified,
        "amplified_share_percent": round(100 * amplified / total, 1) if total else 0.0,
        "distinct_clusters": len(clusters),
        "largest_clusters": [{"cluster_id": cid, "posts": n} for cid, n in ranked],
    })


def _h_watchlist(ctx: ToolContext, args: dict) -> ToolResult:
    active = ctx.session.exec(
        select(func.count()).select_from(WatchlistItem)
        .where(col(WatchlistItem.active) == True)).one()  # noqa: E712
    by_kind = ctx.session.exec(
        select(WatchlistItem.kind, func.count())
        .where(col(WatchlistItem.active) == True)  # noqa: E712
        .group_by(col(WatchlistItem.kind))).all()
    by_priority = ctx.session.exec(
        select(WatchlistItem.priority, func.count())
        .where(col(WatchlistItem.active) == True)  # noqa: E712
        .group_by(col(WatchlistItem.priority))).all()

    return ToolResult({
        "active_terms": active,
        "by_kind": {str(k): int(n) for k, n in by_kind},
        "by_priority": {str(p): int(n) for p, n in by_priority},
    })


def _h_emerging(ctx: ToolContext, args: dict) -> ToolResult:
    from app.services.emerging import detect_emerging

    hours = _clamp_hours(args.get("hours"))
    try:
        found = detect_emerging(hours)
    except Exception:
        log.exception("emerging-topic detection failed")
        return ToolResult({"error": "Emerging-topic detection is unavailable."})

    items = found.get("items", [])[: _clamp_limit(args.get("limit"), 3, 8)]
    summary = [{"platform": i.get("platform"),
                "author_handle": guard.sanitise_untrusted(
                    str(i.get("author_handle", "")), 40),
                "threat_label": i.get("threat_label"),
                "threat_score": i.get("threat_score"),
                "spread_score": i.get("spread_score"),
                "independent_sources": i.get("source_count")} for i in items]

    return ToolResult(
        payload={"window_hours": hours, "count": found.get("count", len(items)),
                 "unverified_claims_spreading": summary},
        display={"items": [{**i, "text": guard.sanitise_untrusted(
            str(i.get("text", "")))} for i in items]})


def _h_model_status(ctx: ToolContext, args: dict) -> ToolResult:
    from app.services import groq_client, model_info

    try:
        models = model_info.get_models()
    except Exception:
        log.exception("model registry unavailable")
        models = {}

    ensemble = models.get("ensemble", {})
    return ToolResult({
        "nlp_mode": settings.NLP_MODE,
        "sentiment_decision_rule": ensemble.get("decision_rule"),
        "sentiment_models": [
            {"name": m.get("name"), "family": m.get("family"),
             "live": m.get("live"),
             "accuracy": (m.get("accuracy") or {}).get("accuracy")}
            for m in ensemble.get("models", [])],
        "threat_model": {
            "name": (models.get("threat_model") or {}).get("name"),
            "labels": (models.get("threat_model") or {}).get("labels"),
            "accuracy": (models.get("threat_model") or {}).get("accuracy"),
        },
        "llm_layer_enabled": groq_client.enabled(),
        "alert_threshold": settings.ALERT_THRESHOLD,
        "critical_threshold": settings.CRITICAL_THRESHOLD,
    })


def _h_explain_project(ctx: ToolContext, args: dict) -> ToolResult:
    """Answer a question about how SENTINEL itself works.

    Returns nothing when the knowledge base does not cover the question, which
    is the point — the agent is instructed to say it does not know rather than
    improvise, and improvising is exactly what it would do if handed the
    least-irrelevant paragraph.
    """
    question = str(args.get("question") or "")[:300]
    entries = knowledge.search(question, limit=_clamp_limit(args.get("limit"), 3, 5))
    return ToolResult({
        "question": question,
        "found": len(entries),
        "documentation": [{"topic": e.title, "content": e.body} for e in entries],
        "note": ("No documentation matched. Say you do not have that detail "
                 "rather than guessing." if not entries else
                 "This is the product's own documentation. Answer from it only."),
    })


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


def _h_navigate(ctx: ToolContext, args: dict) -> ToolResult:
    """Open a dashboard page.

    The only tool with an effect outside the answer, and the reason navigation
    targets are safe: the model chooses a *label*, this resolves the label
    against a fixed table, and an unknown label opens nothing. A path never
    travels from the model to the browser.
    """
    label = str(args.get("page") or "").strip().lower()
    path = _PAGES.get(label)
    if path is None and re.fullmatch(r"[a-z][a-z \-]{0,40}", label):
        # The model sometimes says "the alerts page" rather than "alerts".
        # Matched on word boundaries, and only for a value that is plainly a
        # spoken label: a bare substring search resolves "javascript:alert(1)"
        # to the alerts page, which is how a fuzzy match becomes an open
        # redirect. Longest first, so "threat feed" beats "feed".
        for known in sorted(_PAGES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(known)}\b", label):
                path, label = _PAGES[known], known
                break
    if path is None:
        return ToolResult({"opened": False, "reason": f"There is no '{label}' page.",
                           "available_pages": sorted(set(_PAGES))})
    return ToolResult({"opened": True, "page": label}, navigate=path)


def _h_run_sql(ctx: ToolContext, args: dict) -> ToolResult:
    """Free-form read-only SQL against the restricted views.

    The escape hatch for questions the tools above do not have a parameter for.
    See `sandbox.py` for what "restricted" means — in short, three views of
    structured columns, no free text, no writes, and the database enforcing
    that independently of the validator.
    """
    statement = str(args.get("sql") or "")
    try:
        result = sandbox.run(statement)
    except sandbox.SqlRejected as exc:
        # Handed back to the model, which usually rewrites the query correctly
        # on the next step. A rejection is not an error worth surfacing to the
        # officer unless every attempt fails.
        return ToolResult({"error": str(exc), "schema": sandbox.SCHEMA_DOC})

    return ToolResult(
        payload={"sql": result.sql, "columns": result.columns, "rows": result.rows,
                 "row_count": result.row_count, "truncated": result.truncated},
        display={"sql": result.sql, "columns": result.columns, "rows": result.rows,
                 "elapsed_ms": result.elapsed_ms})


# ── the registry ────────────────────────────────────────────────────────────

TOOLS: list[Tool] = [
    Tool("situation_brief",
         "Headline numbers for a time window: posts collected, how many cleared "
         "the alert threshold, critical and unactioned alerts, mean threat "
         "score. Use this for 'brief me', 'sitrep', 'what's going on'.",
         _params({"hours": _HOURS}),
         _h_situation_brief),

    Tool("count_posts",
         "Count posts matching any combination of filters, with their mean "
         "threat score. Use for 'how many ...' questions.",
         _params({"hours": _HOURS, "city": _CITY, "platform": _PLATFORM,
                  "sentiment": _SENTIMENT,
                  "language": {"type": "string",
                               "description": "English, Hindi, Gujarati, Hinglish or Mixed."},
                  "threat_label": {"type": "string",
                                   "enum": ["Incitement to Violence", "Inflammatory",
                                            "Fake News", "Neutral"]},
                  "min_threat_score": {"type": "number",
                                       "description": "Only posts scoring at least this (0-100)."},
                  "amplified_only": {"type": "boolean",
                                     "description": "Only posts in a coordinated burst."}}),
         _h_count_posts),

    Tool("breakdown",
         "Group posts by one dimension and return counts and mean threat score "
         "per group. Use for 'by platform', 'which city is worst', 'split by "
         "language'.",
         _params({"dimension": {"type": "string",
                                "enum": sorted(set(_DIMENSIONS)),
                                "description": "What to group by."},
                  "hours": _HOURS, "city": _CITY, "platform": _PLATFORM,
                  "sentiment": _SENTIMENT,
                  "limit": {"type": "integer", "description": "Max groups (default 8)."}},
                 required=["dimension"]),
         _h_breakdown),

    Tool("timeseries",
         "Post volume and mean threat score over time, bucketed by hour for "
         "short windows and by day for long ones. Use for 'is it rising', "
         "'trend over the week', 'when did it spike'.",
         _params({"hours": _HOURS, "city": _CITY, "platform": _PLATFORM,
                  "sentiment": _SENTIMENT}),
         _h_timeseries),

    Tool("trending_hashtags",
         "The most-used hashtags in a window, optionally for one city.",
         _params({"hours": _HOURS, "city": _CITY,
                  "limit": {"type": "integer", "description": "How many (default 5)."}}),
         _h_trending_hashtags),

    Tool("top_posts",
         "The highest-scoring or most recent posts matching the filters, with "
         "their scores, labels and account metadata. The post wording is shown "
         "on the officer's screen but is not returned to you — describe the "
         "scores and say the post is on screen.",
         _params({"hours": _HOURS, "city": _CITY, "platform": _PLATFORM,
                  "sentiment": _SENTIMENT,
                  "order_by": {"type": "string", "enum": ["threat_score", "recent"]},
                  "limit": {"type": "integer", "description": "How many (default 3)."}}),
         _h_top_posts),

    Tool("list_alerts",
         "Recent alerts with severity, status, location and score.",
         _params({"hours": _HOURS, "city": _CITY,
                  "severity": {"type": "string", "enum": ["critical", "high", "medium"]},
                  "status": {"type": "string", "enum": ["new", "acknowledged", "escalated"]},
                  "limit": {"type": "integer", "description": "How many (default 5)."}}),
         _h_list_alerts),

    Tool("city_comparison",
         "Every monitored city side by side: volume, mean threat score, posts "
         "above threshold and alerts raised. Use for 'which city is worst'.",
         _params({"hours": _HOURS}),
         _h_city_comparison),

    Tool("coordination_check",
         "How much of the window looks coordinated rather than organic: "
         "amplified share, number of distinct bursts, largest bursts.",
         _params({"hours": _HOURS, "city": _CITY, "platform": _PLATFORM}),
         _h_coordination),

    Tool("watchlist_status",
         "How many watchlist terms are active, broken down by kind and priority.",
         _params({}),
         _h_watchlist),

    Tool("emerging_claims",
         "Claims that are spreading fast but have only one source and no "
         "independent corroboration — the early-warning view for fake news.",
         _params({"hours": _HOURS,
                  "limit": {"type": "integer", "description": "How many (default 3)."}}),
         _h_emerging),

    Tool("model_status",
         "Which models are running, the ensemble decision rule, measured "
         "accuracy and the configured thresholds. Use for questions about the "
         "system's own accuracy or configuration.",
         _params({}),
         _h_model_status),

    Tool("explain_project",
         "Look up how SENTINEL itself works — architecture, the threat-score "
         "formula, languages, data sources, roles, security, what the assistant "
         "may do. Use this for ANY question about the product rather than "
         "answering from memory.",
         _params({"question": {"type": "string",
                               "description": "The officer's question, verbatim."}},
                 required=["question"]),
         _h_explain_project),

    Tool("run_sql",
         "Read-only SQL for questions the other tools cannot express — unusual "
         "filter combinations, joins between posts and alerts, distinct counts. "
         "SELECT only, against assistant_posts, assistant_alerts and "
         "assistant_watchlist. Post and alert body text is not available here.",
         _params({"sql": {"type": "string",
                          "description": "A single SELECT statement. "
                                         "Schema:\n" + sandbox.SCHEMA_DOC}},
                 required=["sql"]),
         _h_run_sql),

    Tool("navigate",
         "Open a dashboard page for the officer. Call this when they ask to be "
         "taken somewhere, or alongside an answer whose detail lives on a page.",
         _params({"page": {"type": "string", "enum": sorted(set(_PAGES)),
                           "description": "Which page to open."}},
                 required=["page"]),
         _h_navigate),
]

_BY_NAME = {tool.name: tool for tool in TOOLS}


def for_role(role: str) -> list[Tool]:
    """The tools this rank may use. Filtered before the model is told anything,
    so a tool above the caller's rank is not refused — it is invisible."""
    tools = [t for t in TOOLS if at_least(role, t.min_role)]
    if not settings.ASSISTANT_SQL_ENABLED or not at_least(
            role, settings.ASSISTANT_SQL_MIN_ROLE):
        tools = [t for t in tools if t.name != "run_sql"]
    return tools


def schemas_for_role(role: str) -> list[dict]:
    return [tool.schema() for tool in for_role(role)]


def invoke(name: str, args: dict, ctx: ToolContext) -> ToolResult:
    """Run a tool by name, re-checking rank on the way in.

    The rank check is duplicated from `for_role` deliberately. That one decides
    what the model is *shown*; this one decides what actually runs, and a bug
    in the first must not become a privilege escalation in the second.
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        return ToolResult({"error": f"There is no tool called '{name}'.",
                           "available": [t.name for t in for_role(ctx.user.role)]})
    if not at_least(ctx.user.role, tool.min_role):
        return ToolResult({"error": "Your rank does not permit that lookup."})
    if tool.name == "run_sql" and not settings.ASSISTANT_SQL_ENABLED:
        return ToolResult({"error": "Direct SQL is disabled on this instance."})

    if not isinstance(args, dict):
        args = {}
    try:
        return tool.handler(ctx, args)
    except Exception:
        # One failing tool must not take the whole answer down: the agent can
        # still say something useful from the tools that did work.
        log.exception("assistant tool %s failed", name)
        return ToolResult({"error": f"The {name} lookup failed."})


def catalogue(role: str) -> list[dict]:
    """Human-readable capability list for the /capabilities endpoint."""
    return [{"name": t.name, "description": t.description.split(". ")[0] + "."}
            for t in for_role(role)]
