"""The few things the assistant may change, and the two-turn rule that guards them.

Everything else the assistant does is a read. This module is the exception,
and it is kept small and in one file so the whole of it can be reviewed at
once. Nothing here runs on a single utterance:

  1. **Prepare.** The model calls an action tool (`generate_report`,
     `set_watchlist_term`, …). That call validates the request, resolves what
     it refers to ("the #suratflood term", "alert 3f2a…"), and stores it as the
     officer's one *pending* action. Nothing has changed yet. The officer's
     screen shows the action with Confirm / Cancel buttons, and the model asks
     out loud, in the officer's language.
  2. **Confirm.** Only on a *later* turn. Either the officer clicks Confirm, or
     they say yes and the model calls `confirm_action`. The server does not
     take the model's word for that: it checks the officer's own words for that
     turn (`is_affirmation`), and that the action was prepared before the turn
     began. So a model that prepares and confirms in one breath, or a crawled
     post that talks it into confirming, gets "not confirmed" back.

Pending actions expire after `PENDING_TTL_SECONDS` and there is at most one per
officer — preparing another replaces it, so "yes" can only ever mean the last
thing that was read back.

What is deliberately absent: deleting anything (watchlist terms, posts,
reports), the retention purge, retraining a model, anything about officer
accounts, and sending anything outside the building. The rank needed for each
action is the rank the dashboard's own route requires, so the microphone is
never a way around a role check.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlmodel import col, select

from app.models import Alert, Report, WatchlistItem
from app.security.context import Actor, reset_actor, set_actor
from app.security.roles import ADMIN, ANALYST, SUPERVISOR, at_least
from app.services.assistant import guard

log = logging.getLogger("sentinel.assistant.actions")

PENDING_TTL_SECONDS = 120

# ── what counts as "yes" and "no" ───────────────────────────────────────────
#
# Matched on whole tokens, not substrings ("ha" must not fire inside "what"),
# and not with \b, which breaks on the vowel signs of Devanagari and Gujarati.

_AFFIRM = [
    # English
    "yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "go ahead",
    "do it", "proceed", "ok", "okay", "affirmative", "please do",
    # Hindi
    "हाँ", "हां", "हा", "जी", "जी हाँ", "ठीक है", "कर दो", "कर दीजिए", "करो",
    "पक्का", "बिल्कुल", "ओके",
    # Hinglish
    "haan", "han", "haa", "ji", "haan ji", "theek hai", "thik hai", "kar do",
    "kardo", "kar dijiye", "karo", "pakka", "bilkul",
    # Gujarati
    "હા", "હાં", "હા જી", "બરાબર", "કરી દો", "કરી નાખો", "કરો", "ઠીક છે",
    "ચોક્કસ", "ઓકે",
    # Gujlish
    "ha", "kari do", "kari nakho", "kari nakh", "barabar", "thik che",
    "thik chhe", "saru", "chokkas",
]
_NEGATE = [
    "no", "nope", "cancel", "don't", "dont", "do not", "stop", "not now",
    "never", "wait", "abort",
    "नहीं", "नही", "ना", "मत", "रहने दो", "रुको", "कैंसल",
    "nahi", "nahin", "nai", "mat", "rehne do", "rahne do", "ruko",
    "ના", "નહીં", "નહિ", "રહેવા દો", "રોકો", "રદ કરો", "કેન્સલ",
    "na", "rehva do", "raheva do", "roko", "rad karo",
]
_TOKEN_SPLIT = re.compile(r"[\s,.!?।॥;:\"()\[\]\-]+")
#: "yes" has to come early. "Is it yes or no?" is not a confirmation.
_AFFIRM_WITHIN = 6


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(guard.normalise(text)) if t]


def _has_phrase(tokens: list[str], phrases: list[str], within: int | None = None) -> bool:
    window = tokens[:within] if within else tokens
    for phrase in phrases:
        parts = phrase.split()
        n = len(parts)
        for i in range(len(window) - n + 1):
            if window[i:i + n] == parts:
                return True
    return False


def is_negation(text: str) -> bool:
    return _has_phrase(_tokens(text), _NEGATE)


def is_affirmation(text: str) -> bool:
    """The officer said yes — in English, Hindi, Gujarati, Hinglish or Gujlish
    — and did not also say no."""
    tokens = _tokens(text)
    return (_has_phrase(tokens, _AFFIRM, within=_AFFIRM_WITHIN)
            and not _has_phrase(tokens, _NEGATE))


# ── the pending store ───────────────────────────────────────────────────────

@dataclass
class Pending:
    id: str
    action: str
    args: dict
    summary: str
    user_id: str
    created: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return time.monotonic() - self.created > PENDING_TTL_SECONDS

    def card(self) -> dict:
        """What the officer's screen shows while it waits."""
        return {"type": "confirm", "action_id": self.id, "summary": self.summary,
                "expires_in": max(0, int(PENDING_TTL_SECONDS - (time.monotonic() - self.created)))}


_pending: dict[str, Pending] = {}


def pending_for(user_id: str) -> Pending | None:
    item = _pending.get(user_id)
    if item is not None and item.expired():
        _pending.pop(user_id, None)
        return None
    return item


def clear(user_id: str) -> None:
    _pending.pop(user_id, None)


# ── outcomes ────────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    """What an executed action hands back: words for the model, and effects
    for the officer's screen (a page to open, a file to download)."""
    payload: dict
    navigate: str | None = None
    client_actions: list[dict] = field(default_factory=list)


class Refused(ValueError):
    """The request cannot be prepared — the message says why, for the model."""


Describe = Callable[[Any, dict], tuple[str, dict]]
Execute = Callable[[Any, dict], Awaitable[Outcome]]


@dataclass(frozen=True)
class Spec:
    min_role: str
    describe: Describe       # (ctx, args) -> (summary, resolved args); raises Refused
    execute: Execute         # (ctx, resolved args) -> Outcome


def _actor(user) -> Actor:
    return Actor(id=str(getattr(user, "id", "") or ""), username=user.username,
                 role=user.role, badge=str(getattr(user, "badge_number", "") or ""))


def _audit(ctx, action: str, target: str, details: dict) -> None:
    from app.services.audit import log_action
    log_action(ctx.session, action, target, {**details, "via": "assistant"},
               actor=_actor(ctx.user))


#: Background jobs started by a confirmed action. Held so the event loop does
#: not garbage-collect a running task.
_jobs: set[asyncio.Task] = set()


def _background(coro, label: str) -> None:
    task = asyncio.create_task(coro)
    _jobs.add(task)

    def _done(t: asyncio.Task) -> None:
        _jobs.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.warning("assistant job %s failed: %s", label, t.exception())
    task.add_done_callback(_done)


# ── generate_report ─────────────────────────────────────────────────────────

_REPORT_KINDS = {"situation": "incident", "incident": "incident",
                 "briefing": "intelligence_briefing",
                 "intelligence_briefing": "intelligence_briefing"}
_FORMATS = ("pdf", "xlsx")


def _hours(value, default: int = 24, ceiling: int = 720) -> int:
    try:
        return max(1, min(int(value), ceiling))
    except (TypeError, ValueError):
        return default


def _describe_report(ctx, args: dict) -> tuple[str, dict]:
    kind = _REPORT_KINDS.get(str(args.get("kind") or "situation").lower(), "incident")
    hours = _hours(args.get("hours"))
    title = guard.sanitise_untrusted(str(args.get("title") or ""), 80)
    fmt = str(args.get("download") or "").lower()
    fmt = fmt if fmt in _FORMATS else ""
    what = "an intelligence briefing" if kind == "intelligence_briefing" else "a situation report"
    span = f"the last {hours} hours" if hours < 48 else f"the last {round(hours / 24)} days"
    summary = f"Generate {what} for {span}"
    if fmt:
        summary += f" and download it as {fmt.upper()}"
    return summary, {"kind": kind, "hours": hours, "title": title, "download": fmt}


async def _execute_report(ctx, args: dict) -> Outcome:
    from app.services.report_service import generate_report
    report = await asyncio.to_thread(generate_report, title=args["title"],
                                     period_hours=args["hours"], kind=args["kind"])
    if args["kind"] == "intelligence_briefing":
        try:
            from app.services.groq_verifier import summarize_briefing
            report.payload["summary"] = await summarize_briefing(report.payload["summary"])
            fresh = ctx.session.get(Report, report.id)
            if fresh is not None:
                fresh.payload = {**fresh.payload, "summary": report.payload["summary"]}
                ctx.session.add(fresh)
                ctx.session.commit()
        except Exception as exc:     # the report stands without the LLM summary
            log.warning("assistant briefing summary failed: %s", exc)
    _audit(ctx, "report_generated", report.id,
           {"kind": args["kind"], "period": args["hours"]})
    effects = []
    path = {"pdf": f"/api/reports/{report.id}/download",
            "xlsx": f"/api/reports/{report.id}/download.xlsx"}.get(args["download"])
    has = {"pdf": bool(report.pdf_path), "xlsx": bool(report.xlsx_path)}
    if path and has.get(args["download"]):
        effects.append({"type": "download", "path": path,
                        "filename": f"SENTINEL_{report.kind}_{report.id}.{args['download']}"})
    return Outcome(
        payload={"done": True, "report_id": report.id, "title": report.title,
                 "pdf_ready": has["pdf"], "xlsx_ready": has["xlsx"],
                 "downloading": bool(effects),
                 "headline": guard.sanitise_untrusted(
                     str((report.payload or {}).get("summary", ""))[:400], 400)},
        navigate=f"/app/reports?open={report.id}", client_actions=effects)


# ── watchlist ───────────────────────────────────────────────────────────────

_KIND_BY_PREFIX = {"#": "hashtag", "@": "account"}
_PRIORITIES = ("low", "medium", "high", "critical")


def _clean_term(raw) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(raw or "")).strip()
    return re.sub(r"\s+", " ", text)[:80]


def _find_terms(ctx, term: str) -> list[WatchlistItem]:
    bare = term.lstrip("#@").lower()
    rows = ctx.session.exec(select(WatchlistItem)).all()
    exact = [w for w in rows if w.value.lstrip("#@").lower() == bare]
    if exact:
        return exact
    return [w for w in rows if bare and bare in w.value.lower()][:5]


def _describe_watch_toggle(ctx, args: dict) -> tuple[str, dict]:
    term = _clean_term(args.get("term"))
    if not term:
        raise Refused("Say which watchlist term to switch on or off.")
    active = args.get("active")
    if isinstance(active, str):
        active = active.strip().lower() in ("true", "on", "yes", "1", "active", "enable")
    if active is None:
        raise Refused("Say whether the term should be switched on or off.")
    found = _find_terms(ctx, term)
    if not found:
        raise Refused(f"There is no watchlist term matching '{term}'. "
                      "It can be added with add_watchlist_term.")
    if len(found) > 1 and len({w.value.lower() for w in found}) > 1:
        raise Refused("That matches several terms: "
                      + ", ".join(sorted({w.value for w in found})[:5])
                      + ". Ask the officer which one.")
    item = found[0]
    if bool(item.active) == bool(active):
        raise Refused(f"'{item.value}' is already {'on' if active else 'off'}.")
    verb = "Resume watching" if active else "Stop watching"
    return f"{verb} the {item.kind} '{item.value}'", {"id": item.id, "active": bool(active)}


async def _execute_watch_toggle(ctx, args: dict) -> Outcome:
    from app.services.scheduler import invalidate_watch_terms
    item = ctx.session.get(WatchlistItem, args["id"])
    if item is None:
        return Outcome({"done": False, "error": "That watchlist term no longer exists."})
    item.active = args["active"]
    ctx.session.add(item)
    ctx.session.commit()
    invalidate_watch_terms()
    _audit(ctx, "watchlist_update", item.id, {"value": item.value, "active": item.active})
    return Outcome({"done": True, "term": item.value, "active": item.active},
                   navigate="/app/watchlist")


def _describe_watch_add(ctx, args: dict) -> tuple[str, dict]:
    from app.services.assistant.tools import _canonical_city
    value = _clean_term(args.get("term"))
    if len(value.lstrip("#@")) < 2:
        raise Refused("Say the word, #hashtag or @account to add.")
    kind = str(args.get("kind") or "").lower()
    if kind not in ("keyword", "hashtag", "account", "location"):
        kind = _KIND_BY_PREFIX.get(value[0], "")
        if not kind:
            kind = "location" if _canonical_city(value) else "keyword"
    priority = str(args.get("priority") or "medium").lower()
    if priority not in _PRIORITIES:
        priority = "medium"
    existing = [w for w in _find_terms(ctx, value)
                if w.value.lstrip("#@").lower() == value.lstrip("#@").lower()]
    if existing:
        w = existing[0]
        raise Refused(f"'{w.value}' is already on the watchlist and is "
                      f"{'on' if w.active else 'switched off'}."
                      + ("" if w.active else " Use set_watchlist_term to switch it on."))
    return (f"Add the {kind} '{value}' to the watchlist at {priority} priority",
            {"kind": kind, "value": value, "priority": priority})


async def _execute_watch_add(ctx, args: dict) -> Outcome:
    from app.services.scheduler import invalidate_watch_terms
    item = WatchlistItem(kind=args["kind"], value=args["value"], priority=args["priority"],
                         note="added by voice assistant", active=True)
    ctx.session.add(item)
    ctx.session.commit()
    ctx.session.refresh(item)
    invalidate_watch_terms()
    _audit(ctx, "watchlist_add", item.id, {"kind": item.kind, "value": item.value})
    return Outcome({"done": True, "term": item.value, "kind": item.kind},
                   navigate="/app/watchlist")


# ── alerts ──────────────────────────────────────────────────────────────────

_ALERT_STATUSES = {"acknowledged": ANALYST, "acknowledge": ANALYST,
                   "escalated": SUPERVISOR, "escalate": SUPERVISOR}


def _describe_alert(ctx, args: dict) -> tuple[str, dict]:
    raw = str(args.get("status") or "").lower()
    if raw not in _ALERT_STATUSES:
        raise Refused("An alert can be acknowledged or escalated.")
    status = "escalated" if raw.startswith("escalat") else "acknowledged"
    if not at_least(ctx.user.role, _ALERT_STATUSES[raw]):
        raise Refused("Escalating needs supervisor rank.")
    alert_id = str(args.get("alert_id") or "").strip()
    alert = ctx.session.get(Alert, alert_id) if alert_id else None
    if alert is None and alert_id:
        # The model may have only the first characters of the id.
        alert = ctx.session.exec(select(Alert).where(col(Alert.id).startswith(alert_id[:36]))
                                 .limit(2)).first() if len(alert_id) >= 6 else None
    if alert is None:
        raise Refused("Which alert? Call list_alerts first and pass its alert_id.")
    if alert.status == status:
        raise Refused(f"That alert is already {status}.")
    title = guard.sanitise_untrusted(alert.title, 80)
    verb = "Escalate" if status == "escalated" else "Acknowledge"
    where = f" in {alert.location}" if alert.location else ""
    return (f"{verb} the {alert.severity} alert{where}: {title}",
            {"alert_id": alert.id, "status": status})


async def _execute_alert(ctx, args: dict) -> Outcome:
    from app.routers.alerts import _set_status
    token = set_actor(_actor(ctx.user))
    try:
        result = await asyncio.to_thread(_set_status, args["alert_id"], args["status"],
                                         ctx.session)
    finally:
        reset_actor(token)
    payload = {"done": True, "status": args["status"],
               "alert_id": args["alert_id"]}
    if result.get("escalation_report_id"):
        payload["escalation_report_id"] = result["escalation_report_id"]
    return Outcome(payload, navigate="/app/alerts")


# ── maintenance (admin) ─────────────────────────────────────────────────────

_JOBS = {
    "collect_now": "Run a collection pass across all platforms now",
    "backfill_translations": "Translate up to sixty stored posts that have no English gloss",
    "redetect_languages": "Re-run language detection over every stored post",
}


def _describe_maintenance(ctx, args: dict) -> tuple[str, dict]:
    job = str(args.get("job") or "").lower()
    if job not in _JOBS:
        raise Refused("The jobs I can start are: " + ", ".join(_JOBS) + ".")
    return _JOBS[job], {"job": job}


async def _execute_maintenance(ctx, args: dict) -> Outcome:
    from app.database import session_scope
    from app.routers import admin

    job = args["job"]
    if job == "collect_now":
        _background(admin.crawl_now(), job)
    elif job == "backfill_translations":
        _background(admin.translate_missing(limit=60), job)
    else:
        def relabel():
            with session_scope() as s:
                return admin.relabel_languages(s)
        _background(asyncio.to_thread(relabel), job)
    _audit(ctx, f"maintenance_{job}", "", {})
    return Outcome({"done": True, "started": job,
                    "note": "It runs in the background; results show on the System page."},
                   navigate="/app/settings")


SPECS: dict[str, Spec] = {
    "generate_report": Spec(ANALYST, _describe_report, _execute_report),
    "set_watchlist_term": Spec(ANALYST, _describe_watch_toggle, _execute_watch_toggle),
    "add_watchlist_term": Spec(ANALYST, _describe_watch_add, _execute_watch_add),
    "set_alert_status": Spec(ANALYST, _describe_alert, _execute_alert),
    "run_maintenance": Spec(ADMIN, _describe_maintenance, _execute_maintenance),
}


# ── the two turns ───────────────────────────────────────────────────────────

def prepare(name: str, ctx, args: dict) -> tuple[dict, Pending | None]:
    """Validate and park an action. Returns (payload for the model, pending)."""
    spec = SPECS[name]
    if not at_least(ctx.user.role, spec.min_role):
        return {"prepared": False, "error": "Your rank does not permit that."}, None
    try:
        summary, resolved = spec.describe(ctx, args)
    except Refused as exc:
        return {"prepared": False, "error": str(exc)}, None
    item = Pending(id=uuid.uuid4().hex[:10], action=name, args=resolved,
                   summary=summary, user_id=str(ctx.user.id))
    _pending[item.user_id] = item
    return {"prepared": True, "needs_confirmation": True, "action_id": item.id,
            "summary": summary,
            "instruction": ("Nothing has been done yet. Read this summary back to "
                            "the officer in their language and ask them to confirm. "
                            "Call confirm_action only after they say yes in their "
                            "next reply; call cancel_action if they say no.")}, item


async def confirm(ctx, action_id: str = "", *, clicked: bool = False) -> Outcome:
    """Run the officer's pending action, if — and only if — they confirmed it.

    `clicked` is the Confirm button: a separate, deliberate act by whoever is
    signed in, so the spoken-yes check does not apply. Otherwise the officer's
    own words this turn (`ctx.utterance`) must be a yes, and the action must
    have been prepared before this turn started.
    """
    user_id = str(ctx.user.id)
    item = pending_for(user_id)
    if item is None:
        return Outcome({"done": False, "error": "There is nothing waiting to be "
                        "confirmed (or it expired). Prepare the action again."})
    if action_id and action_id != item.id:
        return Outcome({"done": False, "error": "That is not the action waiting "
                        "for confirmation.", "pending_summary": item.summary})
    if not clicked:
        if item.created >= ctx.turn_started:
            return Outcome({"done": False, "error": "Not confirmed. The officer has "
                            "to say yes in their next reply — ask them first."})
        if not is_affirmation(ctx.utterance):
            return Outcome({"done": False, "error": "Not confirmed: the officer's "
                            "last words were not a clear yes. Ask again, or cancel."})
    spec = SPECS[item.action]
    if not at_least(ctx.user.role, spec.min_role):   # rank changed since preparing
        clear(user_id)
        return Outcome({"done": False, "error": "Your rank does not permit that."})
    clear(user_id)
    try:
        outcome = await spec.execute(ctx, item.args)
    except Exception as exc:
        log.exception("assistant action %s failed", item.action)
        return Outcome({"done": False, "error": f"It failed: {type(exc).__name__}."},
                       client_actions=[{"type": "confirm_clear"}])
    outcome.payload.setdefault("summary", item.summary)
    outcome.client_actions.insert(0, {"type": "confirm_clear"})
    log.info("assistant action %s confirmed by %s (%s)", item.action,
             ctx.user.username, "click" if clicked else "voice")
    return outcome


def cancel(ctx) -> dict:
    item = pending_for(str(ctx.user.id))
    clear(str(ctx.user.id))
    return ({"cancelled": True, "summary": item.summary} if item
            else {"cancelled": False, "note": "Nothing was waiting."})


def prompt_note(user_id: str) -> str:
    """A line for the system prompt while something is waiting, so the model
    knows what "yes" refers to."""
    item = pending_for(user_id)
    if item is None:
        return ""
    return (f"PENDING ACTION awaiting the officer's confirmation: \"{item.summary}\" "
            f"(action_id {item.id}). If their message says yes, call confirm_action; "
            "if it says no, call cancel_action; otherwise answer normally and leave it.")


def describe_capabilities() -> list[dict]:
    return [{"action": name, "min_role": spec.min_role} for name, spec in SPECS.items()]


__all__ = ["SPECS", "prepare", "confirm", "cancel", "pending_for", "clear",
           "is_affirmation", "is_negation", "prompt_note", "Outcome", "Pending",
           "describe_capabilities"]
