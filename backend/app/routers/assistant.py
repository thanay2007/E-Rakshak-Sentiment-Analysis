"""SENTINEL — the voice assistant's HTTP surface.

Transport only. Authenticate, rate-limit, refuse, dispatch, audit, serialise —
everything about what the assistant may know or do lives in
`app/services/assistant/`, because that is the part that needs reviewing and it
should not be buried in request handling.

The one piece of policy that stays here is the ordering, and it matters:

    normalise → refuse → dispatch → audit

The refusal check runs *before* anything else looks at the utterance, so "read
the alerts and list the officers" is refused whole rather than answering the
half it liked. Refusals are audited with the reason, because a voice request
for the officer roster is exactly the event a reviewer would want to find
later.

Authentication, the router-wide rate limit and `password_not_expired` are
applied by main.py; this module adds its own tighter budget on top, because a
hot mic in a noisy control room produces traffic an analyst never would.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import settings
from app.database import get_session
from app.models import User
from app.security.deps import current_user
from app.security.ratelimit import rate_limit
from app.services.assistant import agent, guard, knowledge, rules, sandbox, tools
from app.services.audit import log_action

log = logging.getLogger("sentinel.assistant")
router = APIRouter()

_assistant_rate_limit = rate_limit(settings.RATE_LIMIT_ASSISTANT, bucket="assistant")


# ── request / response ──────────────────────────────────────────────────────

class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
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
    # Which tools ran, so the panel can show its working. Names and arguments
    # only — never results, which are already in `data`.
    trace: list[dict] = []
    model: str | None = None


# ── endpoints ───────────────────────────────────────────────────────────────

@router.get("/assistant/capabilities")
def capabilities(user: User = Depends(current_user)) -> dict:
    """What SENTINEL will answer, for this caller's rank.

    Published so the UI never advertises more than the server actually allows,
    and so the limits are inspectable by whoever has to sign off on putting a
    microphone in an operations room.
    """
    return {
        "enabled": settings.ASSISTANT_ENABLED,
        "name": "Sentinel",
        "wake_words": ["hey sentinel", "sentinel"],
        "read_only": True,
        "role": user.role,
        "agent_enabled": settings.ASSISTANT_LLM_FALLBACK,
        "sql_enabled": (settings.ASSISTANT_SQL_ENABLED
                        and any(t.name == "run_sql" for t in tools.for_role(user.role))),
        "capabilities": rules.capabilities(),
        "tools": tools.catalogue(user.role),
        "knowledge_topics": knowledge.topics(),
        "refuses": [
            "officer accounts and credentials",
            "the audit trail",
            "biometric and suspect-registry lookups",
            "any action that changes, actions, exports or deletes data",
            "configuration and secrets",
        ],
        "cities": settings.TARGET_CITIES,
        "examples": rules.EXAMPLES,
    }


@router.post("/assistant/ask", response_model=AskResponse,
             dependencies=[Depends(_assistant_rate_limit)])
async def ask(body: AskRequest, session: Session = Depends(get_session),
              user: User = Depends(current_user)) -> AskResponse:
    if not settings.ASSISTANT_ENABLED:
        raise HTTPException(503, "The voice assistant is disabled on this instance.")

    text = guard.normalise(body.query)[: settings.ASSISTANT_MAX_QUERY_CHARS]
    if not text:
        speech = "I didn't catch that."
        return AskResponse(intent="empty", reply=speech, speech=speech)

    refusal = guard.refusal_for(text)
    if refusal is not None:
        message, reason = refusal
        log_action(session, "assistant_refused", "",
                   {"query": text[:200], "reason": reason})
        return AskResponse(intent="refused", reply=message, speech=message,
                           source="refusal")

    ctx = tools.ToolContext(session=session, user=user, page=body.page)
    intent, result = await agent.answer(text, ctx)

    # Audited per answer with the tools that ran, so the audit trail records
    # what the assistant actually looked at and not merely that it was asked.
    log_action(session, "assistant_query", "",
               {"query": text[:200], "intent": intent,
                "tools": [step.get("tool") for step in result.trace][:8],
                "model": result.model or ""})

    return AskResponse(
        intent=intent, reply=result.reply, speech=result.speech,
        navigate=result.navigate, data=result.data,
        source="agent" if intent == "agent" else
               ("unknown" if intent == "unknown" else "rules"),
        trace=result.trace, model=result.model)


@router.get("/assistant/schema")
def schema(user: User = Depends(current_user)) -> dict:
    """The read-only views the SQL window exposes.

    Served so an officer — or an auditor — can see exactly which columns the
    assistant is able to reach, without reading the source. Absent columns are
    absent capabilities: post text, officer accounts, the audit trail and the
    suspect registry are not projected into any view and cannot be queried.
    """
    permitted = settings.ASSISTANT_SQL_ENABLED and any(
        t.name == "run_sql" for t in tools.for_role(user.role))
    return {
        "enabled": permitted,
        "available": sandbox.available() if permitted else False,
        "views": list(sandbox.ALLOWED_VIEWS),
        "schema": sandbox.SCHEMA_DOC,
        "limits": {"max_rows": sandbox.MAX_ROWS,
                   "max_columns": sandbox.MAX_COLUMNS,
                   "timeout_seconds": sandbox.TIMEOUT_SECONDS,
                   "statements": "a single SELECT, always rolled back"},
    }
