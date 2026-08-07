"""The local-model leg of the LLM chain.

Why this file exists: the assistant's remote models fail *predictably* and at
the worst moment. Groq's free tier is a daily token budget, so the busiest
shift of the month — the one during which an officer most needs to ask "what
is happening in Surat right now" — is exactly the shift that drains it. A
control room that loses its uplink loses the assistant with it, and an
air-gapped installation never had one at all.

So what is tested here is not "Ollama works", which is Ollama's problem. It is
the three decisions around it that are ours:

  1. the local model is reached only after every remote one has failed,
  2. it is reached even when there is no Groq key whatsoever, and
  3. it never answers a tool-calling turn unless it has been explicitly
     declared able to call tools.

The third is the one with teeth. This assistant's entire safety argument is
that it can only state what a tool returned; a model that accepts a `tools`
parameter and then answers from memory produces a fluent, confident, entirely
unsourced claim in front of a police officer. Refusing to answer is the safe
failure and it has to stay the default.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio

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
    """Records every POST and replies from a scripted table keyed by host."""

    def __init__(self, groq: FakeResponse, ollama: FakeResponse) -> None:
        self.groq, self.ollama = groq, ollama
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append((url, kwargs.get("json", {})))
        return self.ollama if "11434" in url else self.groq

    async def aclose(self) -> None:
        pass

    @property
    def models_tried(self) -> list[str]:
        return [body.get("model") for _url, body in self.calls]


@pytest.fixture(autouse=True)
def llm_env(monkeypatch):
    """A two-model Groq chain plus a local model, and no cooldown carried in
    from another test — the cooldown map is module state and would otherwise
    silently shorten the chain here."""
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODELS", ["llama-3.1-8b-instant"])
    monkeypatch.setattr(settings, "GROQ_TOOL_MODELS", ["llama-3.3-70b-versatile"])
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setattr(settings, "OLLAMA_TOOL_MODEL", "")
    monkeypatch.setattr(groq_client, "_cooldown", {})
    monkeypatch.setattr(groq_client, "_last_error", {})
    monkeypatch.setattr(groq_client, "_last_ok", {})
    return monkeypatch


MESSAGES = [{"role": "user", "content": "brief me on Surat"}]


# --- reachability ----------------------------------------------------------

def test_the_assistant_is_available_with_a_local_model_and_no_groq_key(llm_env):
    """`enabled()` gates whether callers attempt an LLM at all. If it kept
    meaning "is there a Groq key", an air-gapped install with a perfectly good
    local model would report the assistant as unavailable and never call it."""
    llm_env.setattr(settings, "GROQ_API_KEY", "")
    assert groq_client.enabled()
    assert not groq_client.groq_enabled()

    llm_env.setattr(settings, "OLLAMA_BASE_URL", "")
    assert not groq_client.enabled()


# --- ordering --------------------------------------------------------------

def test_a_working_groq_model_is_never_undercut_by_the_local_one(llm_env):
    """Local is a fallback, not a preference: a 7B model on CPU is slower and
    weaker than Groq's 70B, so it must not be reached while anything remote
    still answers."""
    client = FakeClient(groq=FakeResponse(200, _answer("From Groq.")),
                        ollama=FakeResponse(200, _answer("From Ollama.")))
    content, used = asyncio.run(groq_client.chat(MESSAGES, client=client))
    assert content == "From Groq."
    assert used == "llama-3.3-70b-versatile"
    assert not any("11434" in url for url, _ in client.calls)


def test_the_local_model_answers_once_every_groq_model_is_drained(llm_env):
    """The whole point. A 429 on every model in the chain is a normal end to a
    busy day on the free tier, and it must not end the assistant with it."""
    client = FakeClient(
        groq=FakeResponse(429, text="rate limit reached, try again in 5m"),
        ollama=FakeResponse(200, _answer("Three critical alerts in Surat.")))
    content, used = asyncio.run(groq_client.chat(MESSAGES, client=client))
    assert content == "Three critical alerts in Surat."
    assert used == "ollama/llama3.1:8b"
    # Both Groq models were genuinely tried before falling through.
    assert client.models_tried[:2] == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def test_no_groq_key_goes_straight_to_the_local_model(llm_env):
    """Not one wasted round trip to an endpoint we have no credential for."""
    llm_env.setattr(settings, "GROQ_API_KEY", "")
    client = FakeClient(groq=FakeResponse(401, text="no key"),
                        ollama=FakeResponse(200, _answer()))
    content, used = asyncio.run(groq_client.chat(MESSAGES, client=client))
    assert content == "Surat is quiet."
    assert used == "ollama/llama3.1:8b"
    assert [url for url, _ in client.calls] == [
        "http://127.0.0.1:11434/v1/chat/completions"]


def test_everything_failing_is_still_a_clean_no_answer(llm_env):
    """Callers branch on (None, None). A dead local server must not turn a
    degraded answer into an exception on the audio path."""
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        ollama=FakeResponse(500, text="model runner crashed"))
    assert asyncio.run(groq_client.chat(MESSAGES, client=client)) == (None, None)


def test_an_unreachable_ollama_is_reported_not_raised(llm_env):
    """The normal state of a machine where nobody started `ollama serve`."""
    class Refusing(FakeClient):
        async def post(self, url, **kwargs):
            if "11434" in url:
                raise ConnectionError("connection refused")
            return await super().post(url, **kwargs)

    client = Refusing(groq=FakeResponse(429, text="drained"),
                      ollama=FakeResponse(200, _answer()))
    assert asyncio.run(groq_client.chat(MESSAGES, client=client)) == (None, None)
    assert "network error" in groq_client._last_error["ollama/llama3.1:8b"]


# --- tool calling ----------------------------------------------------------

TOOLS = [{"type": "function",
          "function": {"name": "threat_feed", "description": "recent posts"}}]


def test_a_tool_turn_is_declined_unless_the_local_model_can_call_tools(llm_env):
    """The failure this assistant cannot absorb.

    Every safety property downstream rests on the answer being assembled from
    tool results. A local model that takes the `tools` parameter and then
    improvises would produce a fluent, sourceless answer that reads exactly
    like a real one — so with no verified tool model declared, the correct
    outcome is no answer.
    """
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        ollama=FakeResponse(200, _answer("I think Surat is fine.")))
    message, used = asyncio.run(
        groq_client.chat_tools(MESSAGES, tools=TOOLS, client=client))
    assert (message, used) == (None, None)
    assert not any("11434" in url for url, _ in client.calls)


def test_a_declared_tool_model_does_get_the_tool_turn(llm_env):
    """Opt in and it works — including carrying the tools through, which is
    what separates this from the case above."""
    llm_env.setattr(settings, "OLLAMA_TOOL_MODEL", "llama3.1:8b")
    call = {"choices": [{"message": {
        "role": "assistant",
        "tool_calls": [{"id": "1", "type": "function",
                        "function": {"name": "threat_feed", "arguments": "{}"}}]}}]}
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        ollama=FakeResponse(200, call))
    message, used = asyncio.run(
        groq_client.chat_tools(MESSAGES, tools=TOOLS, client=client))
    assert used == "ollama/llama3.1:8b"
    assert message["tool_calls"][0]["function"]["name"] == "threat_feed"

    ollama_body = next(body for url, body in client.calls if "11434" in url)
    assert ollama_body["tools"] == TOOLS
    assert ollama_body["tool_choice"] == "auto"


# --- provenance ------------------------------------------------------------

def test_a_local_answer_is_labelled_as_one(llm_env):
    """`model_used` is recorded by callers and lands in the audit trail. "Was
    this produced on our hardware or Groq's" is a question a police deployment
    gets asked, and a bare "llama3.1:8b" does not settle it."""
    client = FakeClient(groq=FakeResponse(429, text="drained"),
                        ollama=FakeResponse(200, _answer()))
    _content, used = asyncio.run(groq_client.chat(MESSAGES, client=client))
    assert used.startswith(groq_client.OLLAMA_PREFIX)


def test_status_lists_the_local_model_and_never_cools_it_down(llm_env):
    """A model on our own hardware has no quota to drain — which is the entire
    reason it sits at the end of the chain."""
    report = groq_client.status()
    assert report["local_fallback"] is True
    local = next(m for m in report["models"]
                 if m["model"].startswith(groq_client.OLLAMA_PREFIX))
    assert local["state"] == "ready"
    assert local["role"] == "local"
    assert local["tools"] is False        # OLLAMA_TOOL_MODEL is unset here


def test_the_local_model_is_primary_when_it_is_the_only_one(llm_env):
    llm_env.setattr(settings, "GROQ_API_KEY", "")
    report = groq_client.status()
    assert [m["role"] for m in report["models"]] == ["primary"]
