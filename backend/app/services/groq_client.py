"""Shared Groq chat client with per-model fallback + cooldown.

Groq free-tier rate limits (RPM/TPM/TPD) are tracked PER MODEL, so when the
primary model's daily token budget drains (HTTP 429), the same request usually
succeeds on a sibling model whose quota is untouched. Every LLM feature in the
app (verify, translate, evidence dossier, briefings) calls through here so all
of them inherit the fallback chain instead of dying with the primary model.

A model that 429s is put on cooldown (parsed from the error's "try again in
Xs" hint when present, otherwise 10 minutes, capped at 30) so background loops
stop hammering a drained model every tick. `status()` exposes the live picture
for the Settings page.
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


def enabled() -> bool:
    return bool(settings.GROQ_API_KEY)


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
    chain = [primary] + [m for m in settings.GROQ_FALLBACK_MODELS if m != primary]
    now = time.time()
    live = [m for m in chain if _cooldown.get(m, 0) <= now]
    # if literally everything is cooling down, retry the chain anyway rather
    # than failing without a single attempt
    return live or chain


def _body(model: str, messages: list[dict], temperature: float, json_mode: bool) -> dict:
    body: dict = {"model": model, "temperature": temperature, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if model.startswith("openai/"):  # gpt-oss: don't burn tokens on reasoning
        body["reasoning_effort"] = "low"
    return body


async def chat(messages: list[dict], *, temperature: float = 0.0,
               json_mode: bool = True, model: str | None = None,
               client: httpx.AsyncClient | None = None) -> tuple[str | None, str | None]:
    """One chat completion, walking the fallback chain. Returns
    (content, model_used) — (None, None) when every model failed."""
    if not enabled():
        return None, None
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.GROQ_TIMEOUT_SECONDS,
                                   follow_redirects=True)
    try:
        for m in _chain(model):
            try:
                resp = await client.post(
                    GROQ_URL, json=_body(m, messages, temperature, json_mode),
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}",
                             "Content-Type": "application/json"})
            except Exception as exc:
                _last_error[m] = f"network error: {exc}"
                log.warning("Groq %s network error (%s)", m, exc)
                continue
            if resp.status_code == 200:
                _last_ok[m] = datetime.now(timezone.utc).isoformat()
                _last_error.pop(m, None)
                return resp.json()["choices"][0]["message"]["content"], m
            detail = resp.text[:300]
            _last_error[m] = f"HTTP {resp.status_code}: {detail}"
            if resp.status_code == 429:
                wait = _parse_retry_seconds(detail) or _DEFAULT_COOLDOWN_S
                _cooldown[m] = time.time() + min(wait, _MAX_COOLDOWN_S)
                log.warning("Groq %s rate-limited — cooling down %.0fs, trying next model",
                            m, min(wait, _MAX_COOLDOWN_S))
            else:
                log.warning("Groq %s failed: HTTP %s %s", m, resp.status_code, detail[:160])
        return None, None
    finally:
        if own_client:
            await client.aclose()


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
    chain = [settings.GROQ_MODEL] + [m for m in settings.GROQ_FALLBACK_MODELS
                                     if m != settings.GROQ_MODEL]
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
    return {"enabled": enabled(), "models": models}
