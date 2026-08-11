"""WebSocket /ws/voice — the live audio channel.

Ported from Rapida's `internal/channel/base_streamer.go` and its `Talk()` loop:
a bidirectional stream carrying binary audio one way and JSON control the
other, with the session doing all the thinking.

**Binary is audio, text is control.** WebSocket frames already carry that
distinction, so there is no envelope, no base64 and no per-frame JSON parse on
the hot path. A 20 ms frame is 640 bytes and there are fifty per second per
officer; wrapping each one in JSON would triple the bytes and add a parse to
the most latency-sensitive path in the product.

The two gates from `/ws/live` are applied identically, for the same reasons:

  1. **Origin**, because browsers neither apply the same-origin policy to
     WebSockets nor preflight them, so CORS middleware never sees this
     handshake. Without the check, any site an officer has open could open a
     microphone stream against their session.

  2. **Identity in the first frame, not the query string.** Query strings land
     in access logs, proxy logs and browser history, and a session token in a
     log file is a session token in an incident report.

A third gate is specific to this endpoint: a concurrency cap. Each session
holds a recogniser, a synthesiser and possibly a VAD model, and the failure
mode of an uncapped audio endpoint is one machine exhausting the server for
everyone else on the shift.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import (APIRouter, HTTPException, WebSocket, WebSocketDisconnect,
                     status)

from app.config import settings
from app.database import session_scope
from app.security.deps import authenticate
from app.services.voice import realtime
from app.services.voice import types as voice_types
from app.services.voice.session import SessionConfig, VoiceSession
from app.services.voice.transformer import stt as stt_module
from app.services.voice.transformer import tts as tts_module

log = logging.getLogger("sentinel.voice.channel")
router = APIRouter()

_AUTH_TIMEOUT_SECONDS = 10

#: Live sessions, for the concurrency cap and the diagnostics endpoint.
_sessions: dict[int, VoiceSession] = {}


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return True          # non-browser client
    return origin.rstrip("/") in {o.rstrip("/") for o in settings.CORS_ORIGINS}


def _serialise(packet: voice_types.Packet) -> dict:
    """Packet → the JSON the browser receives.

    Audio never travels this way — it goes as a binary frame — so this is only
    ever control and text, and it stays small enough to send fifty times a
    second without thinking about it.
    """
    payload: dict = {"type": packet.name.value, "context_id": packet.context_id}
    for key, value in vars(packet).items():
        if key in ("context_id", "created_at") or isinstance(value, (bytes, bytearray)):
            continue
        payload[key] = value
    return payload


@router.websocket("/ws/voice")
async def voice_channel(ws: WebSocket) -> None:
    if not settings.VOICE_ENABLED:
        await ws.close(code=status.WS_1011_INTERNAL_ERROR)
        return
    if not _origin_allowed(ws.headers.get("origin", "")):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()

    # ── handshake ───────────────────────────────────────────────────────────
    # First frame: {"type":"auth","token":"…","sample_rate":48000,"page":"/app"}
    try:
        hello = await asyncio.wait_for(ws.receive_json(),
                                       timeout=_AUTH_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, TypeError):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not isinstance(hello, dict) or not hello.get("token"):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if len(_sessions) >= settings.VOICE_MAX_CONCURRENT_SESSIONS:
        await ws.send_json({"type": "error",
                            "message": "Too many voice sessions are open on "
                                       "this server. Try again shortly."})
        await ws.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    # The database session lives for the whole call: the assistant queries
    # through it on every turn, and opening one per turn would cost a
    # connection checkout inside the latency budget.
    with session_scope() as db:
        try:
            user = authenticate(hello["token"], db)
        except HTTPException:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        if user.must_change_password:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        config = SessionConfig(
            language=str(hello.get("language") or settings.VOICE_LANGUAGE),
            page=str(hello.get("page") or "")[:80],
            # The assistant is always on, so it reconnects on its own after an
            # idle close or a dropped network. Only the first connection of a
            # sitting greets: an officer who has been working for an hour does
            # not need to be told the assistant is online every five minutes.
            greeting=(settings.VOICE_GREETING if hello.get("greet") else ""),
            # The browser reports its own capture rate. Assuming 16 kHz when it
            # is really 48 kHz does not error — it transcribes a chipmunk.
            input_sample_rate=int(hello.get("sample_rate")
                                  or voice_types.SAMPLE_RATE),
            stt_provider=str(hello.get("stt") or ""),
            tts_provider=str(hello.get("tts") or ""),
        )

        async def emit(packet: voice_types.Packet) -> None:
            """Session → client. Audio binary, everything else JSON."""
            try:
                if isinstance(packet, voice_types.TextToSpeechAudioPacket) \
                        and packet.audio:
                    await ws.send_bytes(packet.audio)
                    return
                await ws.send_json(_serialise(packet))
            except (WebSocketDisconnect, RuntimeError):
                raise
            except Exception:
                log.exception("failed to emit %s", packet.name)

        # One engine or the other, chosen once per connection. The realtime one
        # is a single Gemini Live stream; the cascade is the VAD → STT → LLM →
        # TTS pipeline. They present the same surface to `_talk` below, so the
        # receive loop never learns which it got.
        if realtime.available():
            session = realtime.GeminiLiveSession(
                user=user, db=db, config=config, emit=emit)
            log.info("voice session open user=%s engine=gemini_live rate=%d",
                     user.username, config.input_sample_rate)
        else:
            session = VoiceSession(user=user, db=db, config=config, emit=emit)
            log.info("voice session open user=%s stt=%s tts=%s rate=%d",
                     user.username, session.stt.name, session.tts.name,
                     config.input_sample_rate)
        _sessions[id(ws)] = session

        try:
            await session.connect()
            await _talk(ws, session)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("voice session failed for %s", user.username)
        finally:
            _sessions.pop(id(ws), None)
            await session.close("disconnected")


async def _talk(ws: WebSocket, session: VoiceSession) -> None:
    """Rapida's `Talk()` — the receive loop.

    One `await` per inbound frame and nothing else, because everything this
    loop touches is on the audio path. Anything slow belongs in a task the
    session owns, not here.
    """
    while True:
        message = await ws.receive()

        if message.get("type") == "websocket.disconnect":
            return

        audio = message.get("bytes")
        if audio:
            await session.push_audio(audio)
            continue

        text = message.get("text")
        if not text:
            continue

        try:
            import json

            command = json.loads(text)
        except ValueError:
            continue
        if not isinstance(command, dict):
            continue

        kind = command.get("type")
        if kind == "text":
            # Typed, or recognised by the browser. Enters the pipeline at the
            # same point a server-side transcript does, so typing and speaking
            # cannot drift apart in behaviour.
            await session.push_text(str(command.get("text", ""))[:2000])
        elif kind == "end_turn":
            await session.finish_turn()
        elif kind == "playback":
            # The browser saying whether sound is coming out of the speakers.
            # Cheap, and the single most load-bearing frame the client sends:
            # without it the recogniser is open to a room containing the
            # assistant's own voice for the whole tail of every answer.
            session.set_playback(bool(command.get("active")))
        elif kind == "interrupt":
            # The client is half-duplex — it stops sending while the speakers
            # are live, so the assistant never hears itself — which means the
            # browser is the only component that can notice an officer talking
            # over the answer. Both engines are told; they act on it
            # differently.
            if hasattr(session, "barge_in"):
                await session.barge_in()
            else:
                await session.on_packet(voice_types.InterruptionDetectedPacket(
                    context_id=session.state.context_id, reason="client"))
        elif kind == "ping":
            state = getattr(session, "state", None)
            if state is not None:
                state.touch()
            await ws.send_json({"type": "pong"})
        elif kind == "close":
            return


@router.get("/api/voice/status")
def voice_status() -> dict:
    """What this instance can do, and how it is performing.

    Unauthenticated on purpose in the same way `/api/health` is: it reports
    provider availability and aggregate latency, never a transcript, a
    username or anything an officer said.
    """
    live = realtime.available()
    return {
        "enabled": settings.VOICE_ENABLED,
        "active_sessions": len(_sessions),
        "max_sessions": settings.VOICE_MAX_CONCURRENT_SESSIONS,
        # Which engine a new connection would get, and on what. The two have
        # very different latency, so a console that reports "voice is on"
        # without saying which one is hiding the thing worth knowing.
        "engine": "gemini_live" if live else "cascade",
        "realtime": {"available": live,
                     "model": settings.GEMINI_LIVE_MODEL if live else ""},
        "configured": {
            "stt": settings.VOICE_STT_PROVIDER,
            "tts": settings.VOICE_TTS_PROVIDER,
            "vad": settings.VOICE_VAD_PROVIDER,
            "denoiser": settings.VOICE_DENOISER,
            "language": settings.VOICE_LANGUAGE,
        },
        # The client needs this to tell an officer how to be heard. A gate
        # nobody was told about is indistinguishable from a broken microphone,
        # and "it stopped listening to me" is how the feature gets switched off.
        "wake_word": {
            "enabled": settings.VOICE_WAKE_WORD_ENABLED,
            "phrase": "Sentinel",
            "follow_up_seconds": settings.VOICE_WAKE_FOLLOW_UP_SECONDS,
        },
        "speech_to_text": stt_module.status(),
        "text_to_speech": tts_module.status(),
        "audio": {"sample_rate": voice_types.SAMPLE_RATE,
                  "frame_ms": voice_types.FRAME_MS,
                  "frame_bytes": voice_types.FRAME_BYTES},
        # Only the cascade measures per-stage latency; the realtime engine has
        # no stages to measure.
        "latency": [s.telemetry.averages() for s in _sessions.values()
                    if hasattr(s, "telemetry")],
    }
