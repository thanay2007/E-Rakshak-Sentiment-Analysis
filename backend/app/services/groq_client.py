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

**Two providers, split by workload.** Gemini answers the assistant (voice and
typed); Groq answers the post pipeline. A caller asks for the one it wants with
`prefer=`, and the other remains behind it as a fallback, so a dead key on
either side costs a first attempt rather than the feature.

There is no local-model tier. This runs as a hosted service, so "a model on
this machine" would mean CPU inference on the web host, on the request path,
with nobody nearby when it fails — see config.py. When every remote model
fails, the LLM-backed features report themselves unavailable, which is honest;
the deterministic rules layer still answers what it can without an LLM.
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

#: `model_used` is written into the audit trail, and "gemini-flash-latest"
#: alone does not say which provider answered — a question a police deployment
#: will be asked.
GEMINI_PREFIX = "gemini/"


def groq_enabled() -> bool:
    return bool(settings.GROQ_API_KEY)


def gemini_enabled() -> bool:
    return bool(settings.GEMINI_API_KEY)


def enabled() -> bool:
    """True when *some* model can be reached.

    Callers use this to decide whether an LLM feature exists at all, so it has
    to mean "there is a model", not "there is a Groq key" — the assistant runs
    on Gemini and must not report itself unavailable just because the pipeline's
    provider is unconfigured.
    """
    return groq_enabled() or gemini_enabled()


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


def _gemini_chain(tools: list[dict] | None) -> list[str]:
    """Gemini models to try, honouring the same per-model cooldowns as Groq.

    Cooldowns matter more here than the shape suggests: the free tier answers a
    drained model with 429 exactly like Groq does (`gemini-pro-latest` already
    does on this key), and without the cooldown the assistant would spend its
    first call of every turn on a model that is known to be out of quota.
    """
    source = (settings.GEMINI_TOOL_MODELS if tools
              else [settings.GEMINI_MODEL] + list(settings.GEMINI_FALLBACK_MODELS))
    chain = list(dict.fromkeys(source))
    now = time.time()
    live = [m for m in chain if _cooldown.get(f"{GEMINI_PREFIX}{m}", 0) <= now]
    return live or chain


async def _complete_gemini(messages: list[dict], *, temperature: float,
                           json_mode: bool, tools: list[dict] | None,
                           client: httpx.AsyncClient) -> tuple[dict | None, str | None]:
    """Gemini, through Google's OpenAI-compatible endpoint.

    Deliberately the same shape as the Groq leg and for the same reason: the
    endpoint speaks the request and response format `_body()` already builds
    and the caller already parses, tool calls included, so nothing above this
    function learns that a second provider exists.
    """
    if not gemini_enabled():
        return None, None

    url = settings.GEMINI_BASE_URL.rstrip("/") + "/chat/completions"
    for model in _gemini_chain(tools):
        label = f"{GEMINI_PREFIX}{model}"
        try:
            resp = await client.post(
                url, json=_body(model, messages, temperature, json_mode, tools),
                headers={"Authorization": f"Bearer {settings.GEMINI_API_KEY}",
                         "Content-Type": "application/json"},
                timeout=settings.GEMINI_TIMEOUT_SECONDS)
        except Exception as exc:
            _last_error[label] = f"network error: {exc}"
            log.warning("Gemini %s network error (%s)", model, exc)
            continue
        if resp.status_code == 200:
            _last_ok[label] = datetime.now(timezone.utc).isoformat()
            _last_error.pop(label, None)
            return resp.json()["choices"][0]["message"], label
        detail = resp.text[:300]
        _last_error[label] = f"HTTP {resp.status_code}: {detail}"
        if resp.status_code == 429:
            wait = _parse_retry_seconds(detail) or _DEFAULT_COOLDOWN_S
            _cooldown[label] = time.time() + min(wait, _MAX_COOLDOWN_S)
            log.warning("Gemini %s rate-limited — cooling down %.0fs, trying next model",
                        model, min(wait, _MAX_COOLDOWN_S))
        elif resp.status_code == 404:
            # Google retires dated model ids for new keys. Long cooldown rather
            # than a retry: this will not fix itself within a session, and the
            # message names the replacement.
            _cooldown[label] = time.time() + _MAX_COOLDOWN_S
            log.warning("Gemini has no model %r for this key (%s) — set "
                        "GEMINI_MODEL to a current alias", model, detail[:160])
        else:
            log.warning("Gemini %s failed: HTTP %s %s", model, resp.status_code,
                        detail[:160])
    return None, None


async def _complete(messages: list[dict], *, temperature: float, json_mode: bool,
                    model: str | None, client: httpx.AsyncClient | None,
                    tools: list[dict] | None = None,
                    chain: list[str] | None = None,
                    prefer: str = "") -> tuple[dict | None, str | None]:
    """One chat completion, walking the fallback chain, then falling back to
    the local model.

    Returns the assistant *message* rather than its content, because a
    tool-calling turn carries its payload in `tool_calls` and has no content at
    all. (None, None) when every model failed.

    `prefer="gemini"` puts the Gemini leg first, with the Groq chain behind it;
    anything else runs Groq first and falls back to Gemini. It is a preference
    and not a switch, so an expired key on either side costs one attempt rather
    than the feature.
    """
    if not enabled():
        return None, None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT_SECONDS,
                                   follow_redirects=True)
    try:
        if prefer == "gemini" and gemini_enabled():
            message, used = await _complete_gemini(
                messages, temperature=temperature, json_mode=json_mode,
                tools=tools, client=client)
            if message is not None:
                return message, used
            log.warning("every Gemini model failed — falling back to Groq")
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

        # Groq is exhausted. If this request did not already start on Gemini,
        # try it now — the two providers have independent quotas, which is the
        # whole reason for keeping both.
        if prefer != "gemini" and gemini_enabled():
            if groq_chain:
                log.warning("every Groq model failed — falling back to Gemini")
            return await _complete_gemini(
                messages, temperature=temperature, json_mode=json_mode,
                tools=tools, client=client)

        log.warning("no model answered — the LLM layer is unavailable")
        return None, None
    finally:
        if own_client:
            await client.aclose()


async def chat(messages: list[dict], *, temperature: float = 0.0,
               json_mode: bool = True, model: str | None = None,
               client: httpx.AsyncClient | None = None,
               prefer: str = "") -> tuple[str | None, str | None]:
    """One chat completion, walking the fallback chain. Returns
    (content, model_used) — (None, None) when every model failed."""
    message, used = await _complete(messages, temperature=temperature,
                                    json_mode=json_mode, model=model, client=client,
                                    prefer=prefer)
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
                     client: httpx.AsyncClient | None = None,
                     prefer: str = "") -> tuple[dict | None, str | None]:
    """A tool-calling turn. Returns (assistant_message, model_used).

    The caller inspects `message["tool_calls"]`; an absent or empty list means
    the model is done and `message["content"]` is the answer. JSON mode is off
    — it is mutually exclusive with tool calling on this API.
    """
    return await _complete(messages, temperature=temperature, json_mode=False,
                           model=model, client=client, tools=tools,
                           chain=_tool_chain(model), prefer=prefer)


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
    models = []

    # Listed first because the assistant tries it first — the Settings page
    # should read in the order a request actually walks.
    if gemini_enabled():
        for m in list(dict.fromkeys([settings.GEMINI_MODEL]
                                    + list(settings.GEMINI_FALLBACK_MODELS))):
            label = f"{GEMINI_PREFIX}{m}"
            cd = _cooldown.get(label, 0)
            models.append({
                "model": label,
                "role": "assistant" if m == settings.GEMINI_MODEL else "assistant_fallback",
                "state": "cooling_down" if cd > now else "ready",
                "cooldown_seconds_left": max(0, round(cd - now)) if cd > now else 0,
                "last_ok": _last_ok.get(label),
                "last_error": _last_error.get(label),
                "tools": m in settings.GEMINI_TOOL_MODELS,
            })

    chain = (list(dict.fromkeys([settings.GROQ_MODEL]
                                + list(settings.GROQ_FALLBACK_MODELS)))
             if groq_enabled() else [])
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

    return {"enabled": enabled(), "models": models,
            # No local tier any more — kept in the payload because the Settings
            # page reads it, and reporting False is the accurate answer rather
            # than a missing key the UI has to guess about.
            "local_fallback": False,
            # Which provider each workload starts on, so the page can say why
            # the assistant and the feed are answered by different models.
            "assistant_provider": (settings.ASSISTANT_LLM_PROVIDER
                                   if gemini_enabled() else "groq"),
            "pipeline_provider": "groq" if groq_enabled() else "gemini"}
