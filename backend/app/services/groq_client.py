"""Shared Groq chat client with per-model fallback + cooldown.

Groq free-tier rate limits (RPM/TPM/TPD) are tracked PER MODEL, so when the
primary model's daily token budget drains (HTTP 429), the same request usually
succeeds on a sibling model whose quota is untouched. Every LLM feature in the
app (verify, translate, evidence dossier, briefings, the voice assistant) calls
through here so all of them inherit the fallback chain instead of dying with
the primary model.

A model that 429s is put on cooldown (parsed from the error's "try again in
Xs" hint when present, otherwise 10 minutes, capped at 30) so background loops
stop hammering a drained model every tick. `status()` exposes the live picture
for the Settings page.

**Ollama is the last link in that chain**, and the only one that does not
depend on anything outside this machine. When every Groq model has failed —
the daily budget drained, the key revoked, the uplink down — a locally served
model still answers, and for a police control room that is the difference
between a degraded assistant and no assistant during exactly the incident
that drained the quota in the first place. With no Groq key at all it is not a
fallback but the whole LLM layer, which is what makes an air-gapped
installation possible.

It is last rather than first on quality: a 7B model on local CPU is slower and
weaker than Groq's 70B, so it is what the product falls back *to*, never what
it prefers. The one thing it is not allowed to do quietly is tool calling —
see OLLAMA_TOOL_MODEL in config.py for why that needs its own switch.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

import httpx

from app.config import settings

log = logging.getLogger("sentinel.groq")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_DEFAULT_COOLDOWN_S = 600
_MAX_COOLDOWN_S = 1800

# model -> unix timestamp until which it is considered drained
_cooldown: dict[str, float] = {}
# model -> short human note about the last failure (for the Settings page)
_last_error: dict[str, str] = {}
# model -> iso timestamp of last successful completion
_last_ok: dict[str, str] = {}

_RETRY_RE = re.compile(r"try again in ([0-9hms.]+)")

#: How a locally served model is named in logs, `status()` and the
#: `model_used` every caller records. Prefixed so an audit trail can always
#: answer "was this answer produced on our hardware or Groq's" — which is a
#: question a police deployment will be asked, and one that a bare model name
#: like "llama3.1:8b" does not settle.
OLLAMA_PREFIX = "ollama/"


def ollama_enabled() -> bool:
    return bool(settings.OLLAMA_BASE_URL and settings.OLLAMA_MODEL)


def groq_enabled() -> bool:
    return bool(settings.GROQ_API_KEY)


def enabled() -> bool:
    """True when *some* model can be reached.

    Callers use this to decide whether an LLM feature exists at all, so it has
    to mean "there is a model", not "there is a Groq key" — otherwise an
    air-gapped install with a perfectly good local model reports the assistant
    as unavailable and never calls it.
    """
    return groq_enabled() or ollama_enabled()


def _parse_retry_seconds(message: str) -> float | None:
    m = _RETRY_RE.search(message)
    if not m:
        return None
    total, num = 0.0, ""
    for ch in m.group(1):
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in "hms" and num:
            total += float(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
    return total or None


def _chain(model: str | None) -> list[str]:
    primary = model or settings.GROQ_MODEL
    # Dedupe while keeping order — the primary may also be in the fallback list.
    chain = list(dict.fromkeys([primary] + list(settings.GROQ_FALLBACK_MODELS)))
    now = time.time()
    live = [m for m in chain if _cooldown.get(m, 0) <= now]
    # if literally everything is cooling down, retry the chain anyway rather
    # than failing without a single attempt
    return live or chain


def _body(model: str, messages: list[dict], temperature: float, json_mode: bool,
          tools: list[dict] | None = None) -> dict:
    body: dict = {"model": model, "temperature": temperature, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        # `auto` rather than `required`: the assistant's last step is a plain
        # spoken answer with no tool call in it, and forcing a call there makes
        # the model invent a lookup it does not need.
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if model.startswith("openai/"):  # gpt-oss: don't burn tokens on reasoning
        body["reasoning_effort"] = "low"
    return body


async def _complete_ollama(messages: list[dict], *, temperature: float,
                           json_mode: bool, tools: list[dict] | None,
                           client: httpx.AsyncClient) -> tuple[dict | None, str | None]:
    """The local model, through Ollama's OpenAI-compatible endpoint.

    That endpoint is the reason this is thirty lines and not a second client:
    the request and response shapes are the ones the Groq path already builds
    and already parses, tool calls included, so nothing above this function has
    to know which machine answered.

    A tool-calling request is refused outright unless OLLAMA_TOOL_MODEL names a
    model known to support it. Returning nothing is a degraded assistant;
    returning an answer from a model that silently ignored the tools is a
    confident, well-phrased, unsourced claim in front of a police officer, and
    that is the worse of the two by a distance.
    """
    if not ollama_enabled():
        return None, None
    if tools:
        model = settings.OLLAMA_TOOL_MODEL
        if not model:
            log.info("ollama: no OLLAMA_TOOL_MODEL set — declining the "
                     "tool-calling turn rather than answering unsourced")
            return None, None
    else:
        model = settings.OLLAMA_MODEL

    label = f"{OLLAMA_PREFIX}{model}"
    url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
    body = _body(model, messages, temperature, json_mode, tools)
    try:
        resp = await client.post(url, json=body,
                                 timeout=settings.OLLAMA_TIMEOUT_SECONDS)
    except Exception as exc:
        _last_error[label] = f"network error: {exc}"
        log.warning("Ollama %s unreachable at %s (%s)", model,
                    settings.OLLAMA_BASE_URL, exc)
        return None, None
    if resp.status_code != 200:
        detail = resp.text[:300]
        _last_error[label] = f"HTTP {resp.status_code}: {detail}"
        # 404 here is nearly always "that model was never pulled", which is a
        # one-command fix and worth saying rather than leaving as a status code.
        if resp.status_code == 404:
            log.warning("Ollama has no model %r — run `ollama pull %s`", model, model)
        else:
            log.warning("Ollama %s failed: HTTP %s %s", model, resp.status_code,
                        detail[:160])
        return None, None

    _last_ok[label] = datetime.now(timezone.utc).isoformat()
    _last_error.pop(label, None)
    log.info("answered locally via Ollama %s", model)
    return resp.json()["choices"][0]["message"], label


async def _complete(messages: list[dict], *, temperature: float, json_mode: bool,
                    model: str | None, client: httpx.AsyncClient | None,
                    tools: list[dict] | None = None,
                    chain: list[str] | None = None) -> tuple[dict | None, str | None]:
    """One chat completion, walking the fallback chain, then falling back to
    the local model.

    Returns the assistant *message* rather than its content, because a
    tool-calling turn carries its payload in `tool_calls` and has no content at
    all. (None, None) when every model failed.
    """
    if not enabled():
        return None, None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT_SECONDS,
                                   follow_redirects=True)
    try:
        # No key means no Groq leg at all — the local model is then the whole
        # LLM layer, not a fallback from one.
        groq_chain = (chain if chain is not None else _chain(model)) if groq_enabled() else []
        for m in groq_chain:
            try:
                resp = await client.post(
                    GROQ_URL, json=_body(m, messages, temperature, json_mode, tools),
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}",
                             "Content-Type": "application/json"})
            except Exception as exc:
                _last_error[m] = f"network error: {exc}"
                log.warning("Groq %s network error (%s)", m, exc)
                continue
            if resp.status_code == 200:
                _last_ok[m] = datetime.now(timezone.utc).isoformat()
                _last_error.pop(m, None)
                return resp.json()["choices"][0]["message"], m
            detail = resp.text[:300]
            _last_error[m] = f"HTTP {resp.status_code}: {detail}"
            if resp.status_code == 429:
                wait = _parse_retry_seconds(detail) or _DEFAULT_COOLDOWN_S
                _cooldown[m] = time.time() + min(wait, _MAX_COOLDOWN_S)
                log.warning("Groq %s rate-limited — cooling down %.0fs, trying next model",
                            m, min(wait, _MAX_COOLDOWN_S))
            else:
                log.warning("Groq %s failed: HTTP %s %s", m, resp.status_code, detail[:160])

        # Every remote model is drained, broken or unreachable. Whatever is
        # running on this machine is the last thing between the officer and
        # silence.
        if groq_chain:
            log.warning("every Groq model failed — falling back to the local model")
        return await _complete_ollama(messages, temperature=temperature,
                                      json_mode=json_mode, tools=tools,
                                      client=client)
    finally:
        if own_client:
            await client.aclose()


async def chat(messages: list[dict], *, temperature: float = 0.0,
               json_mode: bool = True, model: str | None = None,
               client: httpx.AsyncClient | None = None) -> tuple[str | None, str | None]:
    """One chat completion, walking the fallback chain. Returns
    (content, model_used) — (None, None) when every model failed."""
    message, used = await _complete(messages, temperature=temperature,
                                    json_mode=json_mode, model=model, client=client)
    if message is None:
        return None, None
    return message.get("content"), used


def _tool_chain(model: str | None) -> list[str]:
    """The fallback chain restricted to models that can call tools.

    Not every model in the general chain supports the tools parameter, and one
    that does not will either error or — worse — quietly answer from memory
    while ignoring the tool list. For an assistant whose entire safety story is
    "it can only see what the tools return", quietly ignoring the tools is the
    failure that matters, so the chain is an explicit allowlist.
    """
    allowed = [m for m in settings.GROQ_TOOL_MODELS]
    chain = [m for m in _chain(model) if m in allowed]
    return chain or allowed


async def chat_tools(messages: list[dict], *, tools: list[dict],
                     temperature: float = 0.0, model: str | None = None,
                     client: httpx.AsyncClient | None = None
                     ) -> tuple[dict | None, str | None]:
    """A tool-calling turn. Returns (assistant_message, model_used).

    The caller inspects `message["tool_calls"]`; an absent or empty list means
    the model is done and `message["content"]` is the answer. JSON mode is off
    — it is mutually exclusive with tool calling on this API.
    """
    return await _complete(messages, temperature=temperature, json_mode=False,
                           model=model, client=client, tools=tools,
                           chain=_tool_chain(model))


def parse_json(content: str) -> dict | None:
    """Parse a JSON completion, salvaging an object embedded in prose."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


async def chat_json(messages: list[dict], *, temperature: float = 0.0,
                    model: str | None = None,
                    client: httpx.AsyncClient | None = None) -> tuple[dict | None, str | None]:
    content, used = await chat(messages, temperature=temperature, json_mode=True,
                               model=model, client=client)
    if content is None:
        return None, None
    return parse_json(content), used


def status() -> dict:
    """Live LLM-layer picture for the Settings page."""
    now = time.time()
    chain = (list(dict.fromkeys([settings.GROQ_MODEL]
                                + list(settings.GROQ_FALLBACK_MODELS)))
             if groq_enabled() else [])
    models = []
    for m in chain:
        cd = _cooldown.get(m, 0)
        models.append({
            "model": m,
            "role": "primary" if m == settings.GROQ_MODEL else "fallback",
            "state": "cooling_down" if cd > now else "ready",
            "cooldown_seconds_left": max(0, round(cd - now)) if cd > now else 0,
            "last_ok": _last_ok.get(m),
            "last_error": _last_error.get(m),
        })

    if ollama_enabled():
        # Never cooled down: a model on our own hardware has no quota to drain,
        # which is the entire reason it is at the end of the chain.
        label = f"{OLLAMA_PREFIX}{settings.OLLAMA_MODEL}"
        models.append({
            "model": label,
            "role": "local" if chain else "primary",
            "state": "ready",
            "cooldown_seconds_left": 0,
            "last_ok": _last_ok.get(label),
            "last_error": _last_error.get(label),
            "tools": bool(settings.OLLAMA_TOOL_MODEL),
        })
    return {"enabled": enabled(), "models": models,
            "local_fallback": ollama_enabled()}
