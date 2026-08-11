"""The two-provider LLM chain.

Why this file exists: the assistant's models fail *predictably* and at the
worst moment. Both free tiers are quota-limited, so the busiest shift of the
month — the one during which an officer most needs to ask "what is happening
in Surat right now" — is exactly the shift that drains one of them.

This replaced a file that tested an Ollama leg at the end of the chain. That
tier is gone (see config.py: a hosted deployment has no GPU to run it on), and
its job is now done by holding keys for two independent providers instead. So
what is tested here is not "Gemini works", which is Google's problem. It is the
four decisions that are ours:

  1. `enabled()` means "some model is reachable", not "Groq is configured",
  2. the preferred provider is tried first and the other is a real fallback
     rather than a config branch — the quotas are independent, which is the
     entire reason for keeping both,
  3. a drained model is remembered, so the next turn does not open on a model
     already known to be out of quota, and
  4. a tool-calling turn only ever goes to a model explicitly declared able to
     call tools.

The fourth is the one with teeth. This assistant's entire safety argument is
that it can only state what a tool returned; a model that accepts a `tools`
parameter and then answers from memory produces a fluent, confident, entirely
unsourced claim in front of a police officer. Refusing to answer is the safe
failure and it has to stay the default.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.config import settings
from app.services import groq_client


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None,
                 text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def _answer(content: str = "Surat is quiet.") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class FakeClient:
    """Records every POST and replies from a scripted table keyed by provider."""

    def __init__(self, groq: FakeResponse, gemini: FakeResponse) -> None:
        self.groq, self.gemini = groq, gemini
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append((url, kwargs.get("json", {})))
        return self.groq if "groq.com" in url else self.gemini

    async def aclose(self) -> None:
        pass

    @property
    def models_tried(self) -> list[str]:
        return [body.get("model") for _url, body in self.calls]

    @property
    def hit_groq(self) -> bool:
        return any("groq.com" in url for url, _ in self.calls)

    @property
    def hit_gemini(self) -> bool:
        return any("groq.com" not in url for url, _ in self.calls)


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    """Two providers, two models each, and no cooldown carried in from another
    test — the cooldown map is module state and would otherwise silently
    shorten the chain here."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODELS", ["llama-3.1-8b-instant"])
    monkeypatch.setattr(settings, "GROQ_TOOL_MODELS", ["llama-3.3-70b-versatile"])
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gm-test")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-flash-latest")
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODELS", ["gemini-3.5-flash"])
    monkeypatch.setattr(settings, "GEMINI_TOOL_MODELS", ["gemini-flash-latest"])
    monkeypatch.setattr(groq_client, "_cooldown", {})
    monkeypatch.setattr(groq_client, "_last_error", {})
    monkeypatch.setattr(groq_client, "_last_ok", {})
    return monkeypatch


MESSAGES = [{"role": "user", "content": "brief me on Surat"}]


# --- reachability ----------------------------------------------------------

def test_either_key_alone_is_enough_to_have_an_assistant(llm_env):
    """`enabled()` gates whether callers attempt an LLM at all. If it kept
    meaning "is there a Groq key", a deployment running the assistant entirely
    on Gemini would report itself unavailable and never call anything."""
    llm_env.setattr(settings, "GROQ_API_KEY", "")
    assert groq_client.enabled()
    assert not groq_client.groq_enabled()

    llm_env.setattr(settings, "GEMINI_API_KEY", "")
    assert not groq_client.enabled()


# --- ordering --------------------------------------------------------------

def test_the_preferred_provider_is_not_undercut_by_the_other(llm_env):
    """`prefer="gemini"` is what the assistant passes. A working Gemini must
    not cost a wasted Groq round trip on every turn."""
    client = FakeClient(groq=FakeResponse(200, _answer("From Groq.")),
                        gemini=FakeResponse(200, _answer("From Gemini.")))
    content, used = asyncio.run(
        groq_client.chat(MESSAGES, client=client, prefer="gemini"))
    assert content == "From Gemini."
    assert used == "gemini/gemini-flash-latest"
    assert not client.hit_groq


def test_groq_answers_once_every_gemini_model_is_drained(llm_env):
    """The whole point of holding two keys. A 429 on every model of one
    provider is a normal end to a busy day, and it must not end the assistant
    with it — the two quotas are independent."""
    client = FakeClient(
        groq=FakeResponse(200, _answer("Three critical alerts in Surat.")),
        gemini=FakeResponse(429, text="rate limit reached, try again in 5m"))
    content, used = asyncio.run(
        groq_client.chat(MESSAGES, client=client, prefer="gemini"))
    assert content == "Three critical alerts in Surat."
    assert used == "llama-3.3-70b-versatile"
    # Both Gemini models were genuinely tried before falling through.
    assert client.models_tried[:2] == ["gemini-flash-latest", "gemini-3.5-flash"]


def test_the_pipeline_starts_on_groq_and_still_reaches_gemini(llm_env):
    """The post-scoring pipeline passes no preference, so it runs Groq-first —
    but a drained Groq must still fall through rather than losing the leg."""
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        gemini=FakeResponse(200, _answer("From Gemini.")))
    content, used = asyncio.run(groq_client.chat(MESSAGES, client=client))
    assert (content, used) == ("From Gemini.", "gemini/gemini-flash-latest")
    assert client.models_tried[:2] == ["llama-3.3-70b-versatile",
                                       "llama-3.1-8b-instant"]


def test_no_groq_key_does_not_waste_a_round_trip(llm_env):
    """Not one call to an endpoint we have no credential for."""
    llm_env.setattr(settings, "GROQ_API_KEY", "")
    client = FakeClient(groq=FakeResponse(401, text="no key"),
                        gemini=FakeResponse(200, _answer()))
    content, _used = asyncio.run(groq_client.chat(MESSAGES, client=client))
    assert content == "Surat is quiet."
    assert not client.hit_groq


def test_everything_failing_is_still_a_clean_no_answer(llm_env):
    """Callers branch on (None, None). Both providers down must not turn a
    degraded answer into an exception on the audio path."""
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        gemini=FakeResponse(500, text="backend error"))
    assert asyncio.run(groq_client.chat(MESSAGES, client=client)) == (None, None)


def test_an_unreachable_provider_is_reported_not_raised(llm_env):
    """A DNS failure or a dropped uplink is a degraded answer, not a 500 in
    front of an officer."""
    class Refusing(FakeClient):
        async def post(self, url, **kwargs):
            if "groq.com" not in url:
                raise ConnectionError("connection refused")
            return await super().post(url, **kwargs)

    client = Refusing(groq=FakeResponse(429, text="drained"),
                      gemini=FakeResponse(200, _answer()))
    assert asyncio.run(
        groq_client.chat(MESSAGES, client=client, prefer="gemini")) == (None, None)
    assert "network error" in groq_client._last_error["gemini/gemini-flash-latest"]


# --- cooldowns -------------------------------------------------------------

def test_a_drained_model_is_not_tried_again_next_turn(llm_env):
    """Without this the assistant spends the first call of every turn on a
    model it already knows is out of quota — which is the single most visible
    latency bug the free tier can produce."""
    class PerModel(FakeClient):
        """429 for the primary only, so the chain is partially drained."""
        async def post(self, url, **kwargs):
            self.calls.append((url, kwargs.get("json", {})))
            if kwargs.get("json", {}).get("model") == "gemini-flash-latest":
                return FakeResponse(429, text="try again in 5m")
            return FakeResponse(200, _answer("From the fallback."))

    client = PerModel(groq=FakeResponse(200, _answer()),
                      gemini=FakeResponse(200, _answer()))
    content, used = asyncio.run(
        groq_client.chat(MESSAGES, client=client, prefer="gemini"))
    assert (content, used) == ("From the fallback.", "gemini/gemini-3.5-flash")
    assert groq_client._cooldown["gemini/gemini-flash-latest"] > time.time()

    # Second turn: the drained primary is skipped outright.
    again = PerModel(groq=FakeResponse(200, _answer()),
                     gemini=FakeResponse(200, _answer()))
    asyncio.run(groq_client.chat(MESSAGES, client=again, prefer="gemini"))
    assert again.models_tried == ["gemini-3.5-flash"]


def test_a_fully_drained_chain_is_retried_rather_than_abandoned(llm_env):
    """The deliberate exception to the rule above. If every model is cooling
    down, trying the chain anyway beats reporting no assistant at all — a
    cooldown is an estimate, and the quota may well have reset."""
    client = FakeClient(groq=FakeResponse(200, _answer()),
                        gemini=FakeResponse(429, text="try again in 5m"))
    asyncio.run(groq_client.chat(MESSAGES, client=client, prefer="gemini"))

    again = FakeClient(groq=FakeResponse(200, _answer()),
                       gemini=FakeResponse(200, _answer("Back up.")))
    content, _used = asyncio.run(
        groq_client.chat(MESSAGES, client=again, prefer="gemini"))
    assert content == "Back up."


def test_a_retired_model_id_is_cooled_down_hard(llm_env):
    """Google retires dated model ids for new keys. A 404 will not fix itself
    within a session, so retrying it every turn is pure latency."""
    client = FakeClient(groq=FakeResponse(200, _answer()),
                        gemini=FakeResponse(404, text="model not found"))
    asyncio.run(groq_client.chat(MESSAGES, client=client, prefer="gemini"))
    left = groq_client._cooldown["gemini/gemini-flash-latest"] - time.time()
    assert left > groq_client._DEFAULT_COOLDOWN_S


# --- tool calling ----------------------------------------------------------

TOOLS = [{"type": "function",
          "function": {"name": "threat_feed", "description": "recent posts"}}]


def test_a_tool_turn_only_reaches_declared_tool_models(llm_env):
    """The failure this assistant cannot absorb.

    Every safety property downstream rests on the answer being assembled from
    tool results. A model that takes the `tools` parameter and then improvises
    would produce a fluent, sourceless answer that reads exactly like a real
    one — so the chain is an explicit allowlist, not "whatever answered".
    """
    llm_env.setattr(settings, "GEMINI_TOOL_MODELS", ["gemini-flash-latest"])
    call = {"choices": [{"message": {
        "role": "assistant",
        "tool_calls": [{"id": "1", "type": "function",
                        "function": {"name": "threat_feed", "arguments": "{}"}}]}}]}
    client = FakeClient(groq=FakeResponse(200, _answer()),
                        gemini=FakeResponse(200, call))
    message, used = asyncio.run(groq_client.chat_tools(
        MESSAGES, tools=TOOLS, client=client, prefer="gemini"))
    assert used == "gemini/gemini-flash-latest"
    assert message["tool_calls"][0]["function"]["name"] == "threat_feed"

    # The non-tool fallback model was never offered the turn.
    assert "gemini-3.5-flash" not in client.models_tried
    body = client.calls[0][1]
    assert body["tools"] == TOOLS and body["tool_choice"] == "auto"


def test_the_groq_tool_chain_excludes_models_that_cannot_call_tools(llm_env):
    """Same allowlist on the other leg. `llama-3.1-8b-instant` is in the
    general chain and not in GROQ_TOOL_MODELS, so it must never see a tool
    turn even when the model above it is drained."""
    llm_env.setattr(settings, "GEMINI_API_KEY", "")
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        gemini=FakeResponse(200, _answer()))
    asyncio.run(groq_client.chat_tools(MESSAGES, tools=TOOLS, client=client))
    assert client.models_tried == ["llama-3.3-70b-versatile"]


# --- provenance ------------------------------------------------------------

def test_a_gemini_answer_is_labelled_with_its_provider(llm_env):
    """`model_used` is recorded by callers and lands in the audit trail. "Which
    provider produced this" is a question a police deployment gets asked, and a
    bare "gemini-flash-latest" beside "llama-3.3-70b-versatile" does not settle
    it as clearly as a prefix does."""
    client = FakeClient(groq=FakeResponse(200, _answer()),
                        gemini=FakeResponse(200, _answer()))
    _content, used = asyncio.run(
        groq_client.chat(MESSAGES, client=client, prefer="gemini"))
    assert used.startswith(groq_client.GEMINI_PREFIX)


def test_status_reports_both_providers_and_no_local_tier(llm_env):
    """The Settings page reads this to explain why the assistant and the feed
    are answered by different models."""
    report = groq_client.status()
    assert report["enabled"] is True
    assert report["local_fallback"] is False
    assert report["assistant_provider"] == settings.ASSISTANT_LLM_PROVIDER
    assert report["pipeline_provider"] == "groq"
    # Gemini is listed first because that is the order a request walks.
    assert report["models"][0]["model"].startswith(groq_client.GEMINI_PREFIX)
    assert report["models"][0]["tools"] is True
