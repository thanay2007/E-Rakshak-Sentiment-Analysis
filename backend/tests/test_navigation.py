"""Voice navigation: "take me to the alerts page".

Two things are being protected here, and they pull against each other.

**Reach.** Navigation resolving in the deterministic rules layer rather than
the model is what makes it feel instant — no round trip, no rate limit, no
chance of the model fumbling it. That only pays off if the rule actually
recognises how officers speak, and the first version did not: its verb list
had "open" and "go to" but not "show me" or "pull up", so "show me the network
graph" fell through to the model, which answered by *speaking the words*
`navigate page graph` out loud.

**Restraint.** The opposite failure is worse. "Show me the alerts" means read
them out; navigating instead takes away both the answer and the page the
officer was reading. So a weak verb only navigates when the destination has no
spoken answer of its own — see `_DESTINATION_ONLY`.

And one invariant the agent must never lose: a path never travels from model
prose to the browser. The model picks a *label*, a fixed table resolves it, and
an unknown label opens nothing — which is what keeps a post under investigation
from steering an officer's screen.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import pytest

from app.services.assistant import agent, guard, rules, tools


def _page_for(text: str) -> str | None:
    hit = rules.match(text)
    if hit is None or hit.intent != "navigate":
        return None
    return hit.args.get("page")


# --- reaching the fast path ------------------------------------------------

@pytest.mark.parametrize("said, page", [
    ("open trends", "trends"),
    ("go to reports", "reports"),
    ("take me to the alerts page", "alerts"),
    ("pull up investigate", "investigate"),
    ("bring up the admin panel", "admin panel"),
    ("head to settings", "settings"),
    ("back to overview", "overview"),
    ("jump to the watchlist", "watchlist"),
    # Weak verbs, destinations with no spoken answer of their own.
    ("show me the network graph", "network"),
    ("show me the threat feed", "threat feed"),
    ("where is the network page", "network"),
    ("let's see the watchlist page", "watchlist"),
])
def test_the_ways_an_officer_asks_to_be_taken_somewhere(said, page):
    assert _page_for(said) == page


def test_navigation_never_needs_the_model():
    """The whole point of resolving here. A page change that waits on a
    completion is a page change the officer notices waiting for — and it fails
    when the rate limit does."""
    hit = rules.match("take me to the network page")
    assert hit is not None and hit.tool == "navigate"


# --- restraint -------------------------------------------------------------

@pytest.mark.parametrize("said, intent", [
    # These have a spoken answer, so a weak verb must not hijack them.
    ("show me the alerts", "alerts"),
    ("show me the top threat", "top_threat"),
    ("what are the trends in Surat", "trends"),
    # "Open" is also the most common adjective on an operations console.
    ("how many critical alerts are open", "alerts"),
    ("are there any open alerts", "alerts"),
])
def test_a_question_with_an_answer_is_answered_not_navigated(said, intent):
    hit = rules.match(said)
    assert hit is not None and hit.intent == intent


def test_an_explicit_page_still_navigates_for_a_content_word():
    """Saying "page" resolves the ambiguity the verb left open — whatever else
    "the alerts page" is, it is not a request to read alerts aloud."""
    assert _page_for("show me the alerts page") == "alerts"


def test_a_navigation_verb_with_no_destination_declines():
    """"Open up the last 24 hours" is a request for content wearing a
    navigation verb. Declining lets a content rule take it."""
    assert _page_for("open up the last twenty four hours") is None


# --- the safety boundary ---------------------------------------------------

def test_every_label_resolves_to_an_internal_path():
    """A path never originates in model prose; it is looked up here. Anything
    escaping this table is an open redirect with a police officer on the other
    end of it."""
    for label, path in tools._PAGES.items():
        assert path.startswith("/app"), f"{label} escapes the app"
        assert "//" not in path and ":" not in path


def test_an_unknown_page_label_opens_nothing():
    ctx = object()
    result = tools._h_navigate(ctx, {"page": "javascript:alert(1)"})
    assert result.navigate is None
    assert result.payload["opened"] is False


# --- a tool call the model wrote out instead of making ---------------------

@pytest.mark.parametrize("content", [
    '<navigate>{"page": "graph"}</navigate>',
    '{"name": "navigate", "arguments": {"page": "network"}}',
    '```json\n{"page": "alerts"}\n```',
    '<tool_call>navigate</tool_call>',
])
def test_a_tool_call_written_as_prose_is_recognised(content):
    """Observed, not imagined: when Groq's 70B returns `tool_use_failed` the
    chain falls to a weaker model, and weaker models emit exactly this. Local
    models via Ollama do it more often still."""
    assert agent._looks_like_a_tool_call(content)


@pytest.mark.parametrize("plain", [
    "No alerts in Surat in the last 24 hours.",
    "Opening alerts.",
    "Surat is at sixty-seven, the highest of the four cities.",
])
def test_a_normal_answer_is_not_mistaken_for_one(plain):
    assert not agent._looks_like_a_tool_call(plain)


def test_the_markup_is_never_read_aloud():
    """The agent retries when it sees one, but a model can produce it on the
    last step too, and what reaches the scrubber is about to be spoken. An
    officer must not hear "navigate page graph"."""
    spoken = guard.scrub('<navigate>{"page": "graph"}</navigate> Opening the network page.')
    assert "navigate" not in spoken.lower()
    assert "page" not in spoken.split("Opening")[0].lower()
    assert "Opening the network page." in spoken


def test_prose_is_still_never_parsed_into_a_navigation():
    """The invariant that makes the whole feature safe. Post text under
    investigation reaches the model, so a model that can be talked into
    emitting a navigate block must not thereby gain the ability to move an
    officer's screen. Recognising the markup is for *retrying and muting* it,
    never for acting on it."""
    import inspect
    source = inspect.getsource(agent.run)
    # The pseudo-call branch may log, re-prompt and continue — it must never
    # assign to `navigate`, which is set only from a real tool result.
    branch = source.split("_looks_like_a_tool_call")[1].split("continue")[0]
    assert "navigate =" not in branch
