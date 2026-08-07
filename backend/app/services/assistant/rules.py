"""The deterministic fast path.

Most of what anyone asks a monitoring assistant is one of about nine
questions, and those nine should not depend on a hosted model being up, on a
rate limit not being drained, or on two seconds of network latency. This layer
recognises them from the transcript, calls the same tool the agent would have
called, and phrases the answer with a hand-written sentence.

It sits in front of the agent rather than beside it, which buys three things:

  **Determinism where it is cheap.** "Brief me" produces the same sentence
  every time, so an officer learns its shape and can stop listening to the
  parts that never change.

  **A floor under the whole feature.** With no API key configured, or with
  every model rate-limited, these nine questions still answer correctly. The
  agent degrades to this rather than to nothing.

  **Speech that was written to be heard.** A model asked for one spoken
  sentence gives you a written one. These were written for audio: no
  parentheses, no lists, no scores read to one decimal place.

Everything else falls through to `agent.py`, which is where the interesting
questions go.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.config import settings
from app.services.assistant import tools
from app.services.assistant.tools import city_in, hours_in, plural

# ── phrasing ────────────────────────────────────────────────────────────────
#
# Each takes the tool's payload and returns what gets said out loud.


def _window(hours: int) -> str:
    if hours == 24:
        return "the last 24 hours"
    if hours == 168:
        return "the last week"
    return f"the last {plural(hours, 'hour')}"


def _say_brief(p: dict) -> str:
    window = _window(p["window_hours"])
    speech = (f"In {window} I've monitored {plural(p['posts_collected'], 'post')}. "
              f"{plural(p['posts_above_alert_threshold'], 'post')} scored above the "
              f"alert threshold, and there "
              f"{'is' if p['unactioned_alerts_total'] == 1 else 'are'} "
              f"{plural(p['unactioned_alerts_total'], 'unactioned alert')}")
    if p["critical_alerts_in_window"]:
        speech += (f", {p['critical_alerts_in_window']} of them critical")
    speech += "."
    if p["amplified_posts"]:
        speech += (f" {plural(p['amplified_posts'], 'post')} showed signs of "
                   f"coordinated amplification.")
    return speech


def _say_alerts(p: dict) -> str:
    total, items = p["matching_alerts"], p["alerts"]
    where = "" if p["city"] == "all" else f" in {p['city']}"
    if not items:
        return f"No alerts{where} in {_window(p['window_hours'])}."
    lead = f"{plural(total, 'alert')}{where} in {_window(p['window_hours'])}."
    spoken = [f"{a['severity']}, {a['title']}, in {a['location']}, "
              f"scoring {round(a['threat_score'])}" for a in items[:3]]
    return lead + " " + ". ".join(spoken) + "."


def _say_trends(p: dict) -> str:
    where = "across all monitored cities" if p["city"] == "all" else f"in {p['city']}"
    tags = p["hashtags"]
    if not tags:
        return f"Nothing is trending {where} in {_window(p['window_hours'])}."
    named = ", ".join(f"{t['tag']} with {plural(t['mentions'], 'mention')}"
                      for t in tags[:3])
    return f"Top trends {where} over {_window(p['window_hours'])}: {named}."


def _say_top_post(p: dict) -> str:
    posts = p["posts"]
    where = "" if p["city"] == "all" else f" in {p['city']}"
    if not posts:
        return f"Nothing scored{where} in {_window(p['window_hours'])}."
    top = posts[0]
    # The score, label, platform and account are spoken; the post's own words
    # are on screen and stay there. They are the suspect's words, not the
    # system's, and that distinction should not be lost in audio.
    return (f"Highest threat{where} is {round(top['threat_score'])} out of 100, "
            f"labelled {top['threat_label']}, from "
            f"{top['author_handle'] or 'an unknown account'} on {top['platform']}. "
            f"It's on screen.")


def _say_breakdown(p: dict) -> str:
    groups = p["groups"]
    if not groups:
        return f"No activity to break down in {_window(p['window_hours'])}."
    named = ", ".join(f"{g['value']}, {plural(g['posts'], 'post')}"
                      for g in groups[:5])
    return (f"Activity by {p['dimension']} over {_window(p['window_hours'])}: "
            f"{named}.")


def _say_city(p: dict) -> str:
    return (f"{p['city_resolved_to']}, {_window(p['window_hours'])}: "
            f"{plural(p['matching_posts'], 'post')} monitored, average threat "
            f"score {round(p['average_threat_score'])}.")


def _say_watchlist(p: dict) -> str:
    return (f"{plural(p['active_terms'], 'active watchlist term')} are being "
            f"matched against every collected post.")


def _say_navigate(p: dict) -> str:
    return f"Opening {p['page']}." if p.get("opened") else p.get("reason", "")


def _say_cities(p: dict) -> str:
    rows = p["cities"]
    if not rows:
        return "No city activity in that window."
    worst = rows[0]
    named = ", ".join(f"{r['city']} at {round(r['average_threat_score'])}"
                      for r in rows[:4])
    return (f"Average threat score by city over {_window(p['window_hours'])}: "
            f"{named}. {worst['city']} is highest.")


HELP_TEXT = (
    "I can brief you on any time window, read out alerts, give you trends and "
    "hashtags for a city, name the highest-scoring post, compare the cities, "
    "break activity down by platform, language or sentiment, show what's "
    "spreading without corroboration, explain how any part of the system works, "
    "and open any page. Ask me anything about the numbers and I'll query them "
    "directly. I'm read-only — I can't change, action or delete anything.")

EXAMPLES = [
    "Brief me on the last 6 hours",
    "How is the threat score calculated?",
    "Which city is worst this week?",
    "How many negative Gujarati posts on Reddit today?",
    "Any critical alerts?",
    "What's spreading without corroboration?",
    "Show me activity by platform",
    "Open the threat feed",
]


# ── matching ────────────────────────────────────────────────────────────────

@dataclass
class RuleHit:
    intent: str
    tool: str
    args: dict
    phrase: Callable[[dict], str]


def _args_window(text: str, **extra) -> dict:
    args = {"hours": hours_in(text)}
    city = city_in(text)
    if city:
        args["city"] = city
    args.update(extra)
    return args


#: "Open" is a navigation verb and also the most common adjective on an
#: operations console: alerts are open, cases are open, an incident stays open.
#: "How many critical alerts are open right now?" is a request for a number,
#: and answering it by navigating is doubly wrong — the officer does not get
#: their count, and the page they were reading is yanked out from under them.
_OPEN_AS_STATE = re.compile(
    r"\b(are|is|was|were|any|many|still|currently|remain(s|ing)?)\b[^.?!]*\bopen\b")

#: An utterance that opens like a question about quantity or state is asking
#: for content whatever verbs it happens to contain.
_ASKING_NOT_TELLING = re.compile(
    r"^\W*(how many|how much|how long|what'?s the (count|number|status)|"
    r"do we have|are there|is there)\b")


#: Verbs that can only mean "take me there". Anything following one of these
#: with a page name is a navigation request and nothing else.
_NAV_VERB_STRONG = re.compile(
    r"\b(open|go to|goto|take me to|get me to|navigate to|switch to|jump to|"
    r"bring up|pull up|head (to|over to)|back to|move to)\b")

#: Verbs that *might* mean navigation and might mean "read it out to me".
#: "Show me the alerts" is a request for the alerts, not for the alerts page;
#: "show me the network graph" cannot be anything but the page. The difference
#: is not in the verb, so it is resolved on the destination below rather than
#: by guessing here.
_NAV_VERB_WEAK = re.compile(
    r"\b(show me|show|display|view|see|let'?s see|i want to see|can i see|"
    r"where is|take a look at)\b")

#: Pages that exist as destinations only — there is no way to answer them out
#: loud, so a weak verb pointed at one is unambiguously navigation. The labels
#: deliberately left out (alerts, trends, watchlist) are the ones with a
#: content rule of their own: "show me the alerts" must keep reading the
#: alerts, because navigating instead would take away the answer *and* the page
#: the officer was reading.
_DESTINATION_ONLY = frozenset({
    "investigate", "investigation", "network", "graph", "reports", "report",
    "settings", "admin", "admin panel", "feed", "threat feed", "posts",
    "overview", "dashboard", "home",
})


def _r_navigate(text: str) -> RuleHit | None:
    if _ASKING_NOT_TELLING.search(text) or _OPEN_AS_STATE.search(text):
        return None
    strong = bool(_NAV_VERB_STRONG.search(text))
    # An explicit "…page" / "…screen" promotes a weak verb: whatever else
    # "show me the alerts page" is, it is not a request to read alerts aloud.
    named_as_page = re.search(r"\b(page|screen|tab|section)\b", text) is not None

    # Longest label first so "threat feed" wins over "feed".
    for label in sorted(tools._PAGES, key=len, reverse=True):
        if not re.search(rf"\b{re.escape(label)}\b", text):
            continue
        if strong or named_as_page or label in _DESTINATION_ONLY:
            return RuleHit("navigate", "navigate", {"page": label}, _say_navigate)
        # A weak verb aimed at a page that can also be answered out loud.
        # Decline, and the content rule further down the list takes it.
        return None
    # A navigation verb with no page named — "open up the last 24 hours" — is
    # someone asking for content, not a destination. Decline and let a content
    # rule take it, or let the agent work it out.
    return None


def _r_city_status(text: str) -> RuleHit | None:
    city = city_in(text)
    if not city:
        # Not a city question after all — "give me a situation report" trips the
        # same words. Decline so the loop keeps looking.
        return None
    return RuleHit("city_status", "count_posts",
                   {"hours": hours_in(text), "city": city}, _say_city)


def _r_platforms(text: str) -> RuleHit | None:
    return RuleHit("platforms", "breakdown",
                   _args_window(text, dimension="platform"), _say_breakdown)


def _r_sentiment_split(text: str) -> RuleHit | None:
    return RuleHit("sentiment_split", "breakdown",
                   _args_window(text, dimension="sentiment"), _say_breakdown)


def _r_alerts(text: str) -> RuleHit | None:
    args = _args_window(text)
    if re.search(r"\bcritical\b", text):
        args["severity"] = "critical"
    return RuleHit("alerts", "list_alerts", args, _say_alerts)


def _r_trends(text: str) -> RuleHit | None:
    return RuleHit("trends", "trending_hashtags", _args_window(text), _say_trends)


def _r_top_threat(text: str) -> RuleHit | None:
    return RuleHit("top_threat", "top_posts",
                   _args_window(text, limit=1), _say_top_post)


def _r_cities(text: str) -> RuleHit | None:
    return RuleHit("city_comparison", "city_comparison",
                   {"hours": hours_in(text)}, _say_cities)


def _r_watchlist(text: str) -> RuleHit | None:
    return RuleHit("watchlist", "watchlist_status", {}, _say_watchlist)


def _r_brief(text: str) -> RuleHit | None:
    return RuleHit("brief", "situation_brief", {"hours": hours_in(text)}, _say_brief)


# Order matters: the first pattern that matches *and whose rule accepts* wins.
# A rule returning None means "those words matched but this isn't my question",
# which is what lets a bare navigation verb or a city-less status query fall
# through to something that can answer it.
#
# Explicit navigation sits first on purpose. "Take me to trends" is a request
# for a destination; "show me the trends" is a request for content, and only
# the first list of verbs below is unambiguous about which.
RULES: list[tuple[str, re.Pattern, Callable[[str], RuleHit | None]]] = [
    # Both verb classes gate the rule; _r_navigate decides which reading wins.
    # Navigation stays first in this list because a request to be taken
    # somewhere is unambiguous once it has survived that check, and resolving
    # it here costs no model round trip at all — the page moves as fast as the
    # officer finished saying it.
    ("navigate", re.compile(_NAV_VERB_STRONG.pattern + "|" + _NAV_VERB_WEAK.pattern),
     _r_navigate),
    ("alerts", re.compile(r"\balerts?\b"), _r_alerts),
    ("top_threat", re.compile(
        r"\b(highest|top|worst|most (severe|dangerous|serious)|biggest)\b.*"
        r"\b(threat|post|score|risk)\b|\bworst post\b"), _r_top_threat),
    ("city_comparison", re.compile(
        r"\b(which|what) city\b|\bcompare (the )?cities\b|\bcity by city\b|"
        r"\bacross (the )?cities\b"), _r_cities),
    ("trends", re.compile(r"\btrend(s|ing)?\b|\bhashtags?\b|"
                          r"\bwhat'?s (hot|spreading)\b"), _r_trends),
    ("sentiment_split", re.compile(
        r"\bsentiment (split|breakdown|mix)\b|\bhow (positive|negative)\b"),
     _r_sentiment_split),
    ("platforms", re.compile(r"\bplatforms?\b|\bby (source|platform)\b"),
     _r_platforms),
    ("watchlist", re.compile(r"\bwatch ?list\b|"
                             r"\bkeywords? (we|being) (watch|monitor)"), _r_watchlist),
    ("city_status", re.compile(
        r"\b(status|situation|how is|how'?s|what'?s happening|update on|"
        r"report on|looking|doing)\b"), _r_city_status),
    ("brief", re.compile(r"\b(brief|briefing|summary|summarise|summarize|"
                         r"overview|sit ?rep|situation report|"
                         r"what'?s going on|catch me up)\b"), _r_brief),
]

_HELP = re.compile(r"\b(help|what can you do|commands|how do you work|"
                   r"what do you do)\b")


def match(text: str) -> RuleHit | None:
    """The deterministic hit for this utterance, or None to hand it to the agent."""
    if _HELP.search(text):
        return RuleHit("help", "", {}, lambda _p: HELP_TEXT)
    for _name, pattern, rule in RULES:
        if not pattern.search(text):
            continue
        hit = rule(text)
        if hit is not None:
            return hit
    return None


def capabilities() -> list[dict]:
    """What the deterministic layer answers, for the capabilities endpoint."""
    return [
        {"intent": "brief", "description": "Situation summary for a time window"},
        {"intent": "alerts", "description": "Recent and critical alerts"},
        {"intent": "trends", "description": "Trending hashtags, optionally per city"},
        {"intent": "city_status", "description": "Volume and threat level for a city"},
        {"intent": "city_comparison", "description": "All monitored cities compared"},
        {"intent": "top_threat", "description": "Highest-scoring post in a window"},
        {"intent": "platforms", "description": "Activity broken down by platform"},
        {"intent": "sentiment_split", "description": "Sentiment mix for a window"},
        {"intent": "watchlist", "description": "How many terms are being matched"},
        {"intent": "navigate", "description": "Open any dashboard page"},
        {"intent": "agent",
         "description": f"Anything else — answered by querying the data and the "
                        f"product documentation "
                        f"({'enabled' if settings.ASSISTANT_LLM_FALLBACK else 'disabled'})"},
    ]
