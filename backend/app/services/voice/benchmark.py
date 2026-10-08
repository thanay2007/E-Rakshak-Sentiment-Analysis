"""Which provider answers an officer faster — Gemini or OpenAI?

    cd backend && python -m app.services.voice.benchmark [--runs 3]

Two measurements, both through the code the console actually runs:

  * **Realtime voice** — each engine (`GeminiLiveSession`,
    `OpenAIRealtimeSession`) is opened as a real session with the real tool
    list, asked the same question, and timed from the question to the first
    tool call and to the first byte of spoken audio. The question goes in as
    text so both engines get identical input; the recognition step this skips
    runs while the officer is still talking on both engines, so it adds little
    to what is measured here.
  * **Assistant text** (typed console and voice cascade) — one tool-calling
    completion per provider, same messages and tools, timed to the reply.

Only read-only questions are asked, so nothing in the database changes. The
result ends with the settings to put in backend/.env: the faster provider
first, the other as its fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models import User
from app.services import groq_client
from app.services.assistant import tools as assistant_tools
from app.services.voice import openai_realtime, realtime
from app.services.voice.session import SessionConfig
from app.services.voice.types import LLMToolInvokedPacket, TextToSpeechAudioPacket

QUESTIONS = [
    "How many critical alerts are there in the last 24 hours?",
    "आज सूरत में कितने पोस्ट आए?",
]
ANSWER_TIMEOUT = 30.0


async def _realtime_once(engine_cls, user: User, db: Session, question: str) -> dict:
    marks: dict[str, float] = {}
    first_audio = asyncio.Event()

    async def emit(packet) -> None:
        now = time.perf_counter()
        if isinstance(packet, LLMToolInvokedPacket):
            marks.setdefault("tool", now)
        if isinstance(packet, TextToSpeechAudioPacket) and packet.audio:
            marks.setdefault("audio", now)
            first_audio.set()

    session = engine_cls(user=user, db=db, config=SessionConfig(), emit=emit)
    t_connect = time.perf_counter()
    await session.connect()
    connected = time.perf_counter() - t_connect
    try:
        start = time.perf_counter()
        await session.push_text(question)
        await asyncio.wait_for(first_audio.wait(), ANSWER_TIMEOUT)
        return {"connect": connected,
                "tool": marks["tool"] - start if "tool" in marks else None,
                "audio": marks["audio"] - start}
    finally:
        await session.close("benchmark")


async def _text_once(prefer: str, question: str, schemas: list[dict]) -> tuple[float, str]:
    messages = [{"role": "system", "content": "You are a police dashboard assistant. "
                 "Answer by calling the right tool."},
                {"role": "user", "content": question}]
    start = time.perf_counter()
    message, model = await groq_client.chat_tools(messages, tools=schemas,
                                                  temperature=0.2, prefer=prefer)
    if message is None:
        raise RuntimeError("no model answered")
    return time.perf_counter() - start, model or ""


def _median(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _fmt(seconds: float | None) -> str:
    return f"{seconds:5.2f}s" if seconds is not None else "   — "


async def main(runs: int) -> None:
    with Session(engine) as db:
        user = db.exec(select(User).where(User.role == "admin")).first() \
            or db.exec(select(User)).first()
        if user is None:
            raise SystemExit("No officer account in the database to run as.")

        # ── realtime voice ─────────────────────────────────────────────────
        print(f"\nRealtime voice — question → first tool call → first audio "
              f"(median of {runs} per question)")
        engines = {"gemini": (realtime, realtime.GeminiLiveSession, settings.GEMINI_LIVE_MODEL),
                   "openai": (openai_realtime, openai_realtime.OpenAIRealtimeSession,
                              settings.OPENAI_REALTIME_MODEL)}
        voice: dict[str, float] = {}
        for name, (module, cls, model) in engines.items():
            if not module.available():
                print(f"  {name:7s} {model:32s} unavailable (no key, or parked "
                      f"{module.cooldown_remaining():.0f}s after a failure)")
                continue
            audio, tool, connect = [], [], []
            try:
                for question in QUESTIONS:
                    for _ in range(runs):
                        r = await _realtime_once(cls, user, db, question)
                        audio.append(r["audio"])
                        tool.append(r["tool"])
                        connect.append(r["connect"])
            except Exception as exc:
                print(f"  {name:7s} {model:32s} FAILED: {str(exc)[:110]}")
                continue
            voice[name] = _median(audio)
            print(f"  {name:7s} {model:32s} connect {_fmt(_median(connect))}  "
                  f"tool {_fmt(_median(tool))}  first audio {_fmt(voice[name])}")

        # ── assistant text ─────────────────────────────────────────────────
        print(f"\nAssistant text — tool-calling reply (median of {runs} per question)")
        schemas = [t.schema() for t in assistant_tools.for_role(user.role)]
        text: dict[str, float] = {}
        for prefer, enabled in (("gemini", groq_client.gemini_enabled()),
                                ("openai", groq_client.openai_enabled())):
            if not enabled:
                print(f"  {prefer:7s} no key")
                continue
            times, models = [], set()
            try:
                for question in QUESTIONS:
                    for _ in range(runs):
                        seconds, model = await _text_once(prefer, question, schemas)
                        times.append(seconds)
                        models.add(model)
            except Exception as exc:
                print(f"  {prefer:7s} FAILED: {str(exc)[:110]}")
                continue
            # The chain falls through to the other provider when one fails,
            # so only count a run that the preferred provider answered.
            if not any(m.startswith({"gemini": groq_client.GEMINI_PREFIX,
                                     "openai": groq_client.OPENAI_PREFIX}[prefer])
                       for m in models):
                print(f"  {prefer:7s} did not answer (answered by {', '.join(models)})")
                continue
            text[prefer] = _median(times)
            print(f"  {prefer:7s} {', '.join(sorted(models)):32s} reply {_fmt(text[prefer])}")

    # ── verdict ────────────────────────────────────────────────────────────
    print("\nRecommended backend/.env settings:")
    if voice:
        order = sorted(voice, key=voice.get) + [p for p in engines if p not in voice]
        print(f'  VOICE_REALTIME_PROVIDERS=["{order[0]}","{order[1]}"]')
    else:
        print("  (no realtime engine answered — keep VOICE_REALTIME_PROVIDERS as is)")
    if text:
        print(f"  ASSISTANT_LLM_PROVIDER={min(text, key=text.get)}")
    else:
        print("  (no text provider answered — keep ASSISTANT_LLM_PROVIDER as is)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=int, default=3)
    asyncio.run(main(max(1, parser.parse_args().runs)))
