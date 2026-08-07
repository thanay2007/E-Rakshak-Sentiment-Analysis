"""The voice pipeline's load-bearing behaviours.

Deliberately not a test per file. These cover the handful of things that, when
they break, present as "the assistant feels broken" rather than as an
exception — which is the class of bug this pipeline is most prone to and the
hardest to find by using it.

Run:  cd backend && python -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from app.config import settings
from app.services.voice import audio
from app.services.voice.transformer import tts
from app.services.voice.aggregator import SentenceAggregator
from app.services.voice.end_of_speech import SilenceBasedEndOfSpeech
from app.services.voice.normalizer import OutputNormalizer
from app.services.voice.state import ConversationState, TurnState
from app.services.voice.types import (EndOfSpeechPacket, LLMResponseDeltaPacket,
                                      LLMResponseDonePacket, SpeechToTextPacket,
                                      TextToSpeechDonePacket,
                                      TextToSpeechTextPacket)
from app.services.voice.vad import EnergyVAD


def _collector():
    """A capturing `on_packet`, since every component emits through one."""
    captured: list = []

    async def on_packet(*packets):
        captured.extend(packets)

    return captured, on_packet


def _tone(ms: int, amplitude: float = 0.4, rate: int = 16000) -> bytes:
    samples = np.sin(2 * np.pi * 220 * np.arange(int(rate * ms / 1000)) / rate)
    return audio.float32_to_pcm16((samples * amplitude).astype(np.float32))


# ── audio ───────────────────────────────────────────────────────────────────

def test_browser_rate_is_resampled_without_changing_duration():
    """48 kHz is what a browser actually captures. Getting this wrong does not
    error — it transcribes a chipmunk — so duration is the assertion."""
    at_48k = _tone(1000, rate=48000)
    at_16k = audio.resample(at_48k, 48000, 16000)
    assert round(audio.duration_ms(at_16k)) == 1000
    # Level must survive too: a resampler that halves amplitude quietly costs
    # the VAD its threshold.
    assert audio.rms(at_16k) == pytest.approx(audio.rms(at_48k), abs=0.02)


def test_frames_are_exactly_20ms_regardless_of_arrival_size():
    """Browsers deliver 128, 1024 or 4096 samples depending on load. Every
    downstream timing figure assumes a fixed frame, so this re-cuts."""
    buffer = audio.FrameBuffer()
    produced = []
    for chunk_size in (100, 1000, 37, 4096):
        produced.extend(buffer.push(_tone(50)[:chunk_size]))
    assert all(len(frame) == audio.FRAME_BYTES for frame in produced)
    assert buffer.pending_bytes < audio.FRAME_BYTES


def test_trailing_partial_frame_is_padded_not_dropped():
    """The last fragment carries the final consonant — the difference between
    "brief" and "brie"."""
    buffer = audio.FrameBuffer()
    buffer.push(b"\x01\x02" * 10)
    assert len(buffer.flush()) == audio.FRAME_BYTES


def test_wav_container_survives_a_roundtrip():
    pcm = _tone(100)
    recovered, rate = audio.from_wav(audio.to_wav(pcm))
    assert recovered == pcm and rate == 16000


# ── VAD ─────────────────────────────────────────────────────────────────────

def test_vad_needs_sustained_speech_to_start_and_sustained_silence_to_stop():
    """The hysteresis, which is the whole reason the VAD is usable. Without it
    the gaps between words read as end-of-turn and the assistant interrupts
    everyone mid-sentence."""
    captured, on_packet = _collector()
    detector = EnergyVAD(on_packet, speech_frames=3, silence_frames=10)

    async def feed(frame: bytes, count: int):
        from app.services.voice.types import DenoisedAudioPacket
        for _ in range(count):
            await detector.process(DenoisedAudioPacket(context_id="t", audio=frame))

    loud, quiet = _tone(20, 0.5), audio.silence(20)

    asyncio.run(feed(loud, 2))
    assert not captured[-1].is_speech, "started on 2 frames; needs 3"

    asyncio.run(feed(loud, 3))
    assert captured[-1].is_speech

    asyncio.run(feed(quiet, 5))
    assert captured[-1].is_speech, "stopped on 5 silent frames; needs 10"

    asyncio.run(feed(quiet, 8))
    assert not captured[-1].is_speech


# ── end of speech ───────────────────────────────────────────────────────────

def test_end_of_speech_fires_once_after_silence():
    captured, on_packet = _collector()

    async def scenario():
        detector = SilenceBasedEndOfSpeech(on_packet, silence_timeout=0.08)
        await detector.process(SpeechToTextPacket(
            context_id="t", text="brief me", is_final=True))
        await asyncio.sleep(0.25)
        await detector.close()

    asyncio.run(scenario())
    finals = [p for p in captured if isinstance(p, EndOfSpeechPacket)]
    assert len(finals) == 1 and finals[0].text == "brief me"


def test_more_speech_cancels_a_pending_end_of_speech():
    """The generation counter. Without it the naive cancel-and-restart races,
    and a question gets cut in half and answered twice."""
    captured, on_packet = _collector()

    async def scenario():
        detector = SilenceBasedEndOfSpeech(on_packet, silence_timeout=0.12)
        await detector.process(SpeechToTextPacket(
            context_id="t", text="show me", is_final=True))
        await asyncio.sleep(0.06)               # timer in flight
        await detector.process(SpeechToTextPacket(
            context_id="t", text="surat", is_final=True))
        await asyncio.sleep(0.30)
        await detector.close()

    asyncio.run(scenario())
    finals = [p for p in captured if isinstance(p, EndOfSpeechPacket)]
    assert len(finals) == 1, "the superseded timer still fired"
    assert finals[0].text == "show me surat"


def test_a_trailing_conjunction_buys_more_time():
    """"Show me Surat and…" is obviously unfinished. Waiting longer costs
    nothing when they were done and saves a wrong answer when they were not."""
    captured, on_packet = _collector()
    detector = SilenceBasedEndOfSpeech(on_packet, silence_timeout=1.0)
    assert detector._timeout_for("show me surat and") > 1.0
    assert detector._timeout_for("show me surat.") < 1.0


def test_interrupt_discards_the_segment():
    captured, on_packet = _collector()

    async def scenario():
        detector = SilenceBasedEndOfSpeech(on_packet, silence_timeout=0.08)
        await detector.process(SpeechToTextPacket(
            context_id="t", text="abandoned", is_final=True))
        await detector.interrupt("t")
        await asyncio.sleep(0.25)
        await detector.close()

    asyncio.run(scenario())
    assert not [p for p in captured if isinstance(p, EndOfSpeechPacket)]


# ── sentence aggregation ────────────────────────────────────────────────────

def _aggregate(chunks: list[str], context: str = "t") -> list[str]:
    captured, on_packet = _collector()

    async def scenario():
        aggregator = SentenceAggregator(on_packet)
        for chunk in chunks:
            await aggregator.aggregate(
                LLMResponseDeltaPacket(context_id=context, text=chunk))
        await aggregator.aggregate(LLMResponseDonePacket(context_id=context))
        await aggregator.close()

    asyncio.run(scenario())
    return [p.text for p in captured if isinstance(p, TextToSpeechTextPacket)]


def test_sentences_are_released_before_generation_finishes():
    """The reason speech starts a second after the question instead of after
    the whole answer."""
    sentences = _aggregate(["In the last 24 hours ", "I monitored 155 posts. ",
                            "Five alerts are open."])
    assert len(sentences) == 2
    assert sentences[0].startswith("In the last 24 hours")


def test_a_decimal_point_is_not_a_sentence_boundary():
    """Every threat score in this product has one decimal place. Splitting
    inside one produces "sixty seven." … "four out of a hundred"."""
    assert _aggregate(["The highest score is 67.4 out of 100 today."]) == \
        ["The highest score is 67.4 out of 100 today."]


def test_a_rank_abbreviation_is_not_a_sentence_boundary():
    assert len(_aggregate(["The Insp. on duty filed the report today."])) == 1


def test_devanagari_danda_is_a_sentence_boundary():
    """Indic transcripts end with ।, not a full stop. A Latin-only boundary set
    silently turns streaming synthesis back into wait-for-everything."""
    sentences = _aggregate(["सूरत में स्थिति सामान्य है। ",
                            "कोई नई चेतावनी नहीं है।"])
    assert len(sentences) == 2


def test_a_new_turn_discards_the_previous_buffer():
    """Buffered text from an abandoned turn must never be spoken into the next
    one — it would answer a question nobody asked."""
    captured, on_packet = _collector()

    async def scenario():
        aggregator = SentenceAggregator(on_packet)
        await aggregator.aggregate(
            LLMResponseDeltaPacket(context_id="first", text="half a sentence"))
        await aggregator.aggregate(
            LLMResponseDeltaPacket(context_id="second",
                                   text="A completely new answer here."))
        await aggregator.aggregate(LLMResponseDonePacket(context_id="second"))
        await aggregator.close()

    asyncio.run(scenario())
    spoken = " ".join(p.text for p in captured
                      if isinstance(p, TextToSpeechTextPacket))
    assert "half a sentence" not in spoken


def test_done_always_terminates_the_stream():
    captured, on_packet = _collector()

    async def scenario():
        aggregator = SentenceAggregator(on_packet)
        await aggregator.aggregate(
            LLMResponseDeltaPacket(context_id="t", text="no terminal punctuation"))
        await aggregator.aggregate(LLMResponseDonePacket(context_id="t"))
        await aggregator.close()

    asyncio.run(scenario())
    assert any(isinstance(p, TextToSpeechDonePacket) for p in captured)


# ── interruption ────────────────────────────────────────────────────────────

def test_the_assistant_does_not_interrupt_itself():
    """Speakers feed the microphone. This is the failure that makes people
    abandon a voice agent in the first minute."""
    state = ConversationState(grace_seconds=0.0, interrupt_frames=3)
    state.begin_speaking("turn-1")
    assert state.suppress_microphone, "the recogniser must not hear the reply"


def test_the_microphone_stays_shut_while_the_speakers_are_still_playing():
    """The bug this exists to prevent: the turn ends when the last audio
    packet is *sent*, which is seconds before the officer stops hearing it.
    For that whole window the old code reopened the recogniser onto a room
    containing the assistant's own voice — so it transcribed itself and
    answered its own reply."""
    state = ConversationState()
    state.begin_speaking("turn-1")
    state.set_client_playback(True)

    state.finish()                      # server: "I have sent everything"
    assert state.state is TurnState.IDLE
    assert state.suppress_microphone, "the speakers are still going"

    state.set_client_playback(False)     # browser: "and now they are quiet"
    assert state.suppress_microphone, "the reverberation tail is still arriving"


def test_the_microphone_reopens_once_the_room_is_quiet():
    state = ConversationState()
    state.begin_speaking("turn-1")
    state.set_client_playback(True)
    state.set_client_playback(False)
    state.finish()
    # Simulate the hangover elapsing rather than sleeping through it.
    state._playback_ended_at = time.monotonic() - 10
    assert not state.suppress_microphone


def test_client_side_synthesis_still_gates_the_microphone():
    """With a browser synthesiser the server sees no audio at all: SPEAKING
    lasts milliseconds while the browser talks for ten seconds. Only the
    client's report covers that."""
    state = ConversationState()
    state.begin_speaking("turn-1")
    state.set_client_playback(True)
    state.finish()
    assert state.suppress_microphone


def test_playback_starts_the_interruption_grace_period():
    """It is playback an officer talks over, not synthesis, and the two can be
    a second apart."""
    state = ConversationState(grace_seconds=5.0, interrupt_frames=1)
    state.begin_speaking("turn-1")
    state._speaking_since = time.monotonic() - 4.9      # nearly out of grace
    state.set_client_playback(True)                     # audio only starts now
    assert not state.observe_speech(True, 1.0), "the grace period must restart"


def test_barge_in_works_against_playback_the_server_thinks_has_ended():
    state = ConversationState(grace_seconds=0.0, interrupt_frames=3)
    state.begin_speaking("turn-1")
    state.set_client_playback(True)
    state.finish()                      # server done sending, browser still talking
    fired = [state.observe_speech(True, 0.95) for _ in range(10)]
    assert fired.count(True) == 1
    assert state.is_stale("turn-1")


def test_a_cough_does_not_interrupt():
    state = ConversationState(grace_seconds=0.0, interrupt_frames=15)
    state.begin_speaking("turn-1")
    for _ in range(5):
        assert not state.observe_speech(True, 0.95)
    assert state.state is TurnState.SPEAKING


def test_sustained_speech_interrupts_exactly_once():
    state = ConversationState(grace_seconds=0.0, interrupt_frames=3)
    state.begin_speaking("turn-1")
    fired = [state.observe_speech(True, 0.95) for _ in range(10)]
    assert fired.count(True) == 1, "an interruption must not repeat"
    assert state.state is TurnState.IDLE


def test_the_grace_period_covers_audio_already_in_the_buffer():
    """For a moment after speech starts, what the microphone hears is the
    previous turn. Reacting there cancels a turn that had not begun."""
    state = ConversationState(grace_seconds=5.0, interrupt_frames=1)
    state.begin_speaking("turn-1")
    assert not state.observe_speech(True, 1.0)


def test_quiet_speech_does_not_meet_the_interruption_bar():
    """Interrupting needs better evidence than noticing a word has begun, so
    the threshold here is stricter than the VAD's own."""
    state = ConversationState(grace_seconds=0.0, interrupt_frames=2,
                              interrupt_probability=0.75)
    state.begin_speaking("turn-1")
    for _ in range(10):
        assert not state.observe_speech(True, 0.6)


def test_packets_from_an_abandoned_turn_are_recognised_as_stale():
    """The LLM and the synthesiser keep producing for a moment after an
    interruption. This is what stops the old answer playing over the new one."""
    state = ConversationState()
    state.begin_speaking("turn-1")
    state.mark_interrupted("turn-1")
    assert state.is_stale("turn-1")
    assert not state.is_stale("turn-2")


def test_the_interrupted_set_does_not_grow_without_bound():
    """A session may run for a whole shift."""
    state = ConversationState()
    for i in range(200):
        state.mark_interrupted(f"turn-{i}")
    assert len(state._interrupted_contexts) <= 32


# ── normalisation ───────────────────────────────────────────────────────────

# Compared case-insensitively: each of these is a fragment, and the chain's
# last stage capitalises a sentence opening. What is under test is which words
# a figure becomes, not where the capital letter lands.
def _spoken(text: str) -> str:
    return OutputNormalizer().normalize(text).lower()


@pytest.mark.parametrize("written,expected", [
    ("67.4", "sixty-seven point four"),
    ("1,50,000", "one lakh fifty thousand"),         # Indian numbering
    ("2 crore", "two crore"),
    ("23%", "twenty-three percent"),
    ("2026", "twenty twenty-six"),                    # not "two thousand..."
    ("168 hours", "seven days"),
])
def test_numbers_are_spoken_the_way_a_person_says_them(written, expected):
    assert expected in _spoken(written)


@pytest.mark.parametrize("written,expected", [
    ("Rs 50,000", "fifty thousand rupees"),
    ("₹1,50,000", "one lakh fifty thousand rupees"),
    ("12 km", "twelve kilometres"),
])
def test_currency_and_units_reach_the_right_words(written, expected):
    assert expected in _spoken(written)


@pytest.mark.parametrize("written,expected", [
    ("The DCP was briefed", "deputy commissioner of police"),
    ("filed an FIR", "f i r"),
    ("the SHO said", "station house officer"),
])
def test_police_abbreviations_are_said_correctly(written, expected):
    assert expected in _spoken(written)


def test_a_sentence_opening_with_a_spelled_number_is_capitalised():
    """Spelling a number yields a lower-case word, and the transcript is read
    as often as it is heard."""
    spoken = OutputNormalizer().normalize("I saw 12 posts. 0 were critical.")
    assert "Zero were critical" in spoken


def test_nothing_unspeakable_survives_the_chain():
    """Markdown, URLs and emoji are artefacts of text being looked at. Read
    aloud they are noise at best and unintelligible at worst."""
    spoken = OutputNormalizer().normalize(
        "**Surat** is highest 😀 — see https://example.com/report for detail")
    for artefact in ("*", "http", "😀", "—"):
        assert artefact not in spoken
    assert "Surat" in spoken


def test_a_handle_is_split_into_pronounceable_words():
    spoken = OutputNormalizer().normalize("Posted by @SantaniSubhajit today")
    assert "Santani Subhajit" in spoken


def test_a_timestamp_is_read_as_a_time():
    spoken = OutputNormalizer().normalize("Alert raised at 14:30")
    assert "half past two" in spoken and "in the afternoon" in spoken


def test_the_chain_never_raises_on_hostile_input():
    """This runs on model output, on every sentence, in front of an officer. A
    regex meeting input its author did not imagine must cost one imperfect
    sentence, not the answer."""
    normalizer = OutputNormalizer()
    for hostile in ("", "   ", "]]}{[[", "\\\\", "999999999999999999999999",
                    "🙂" * 200, "0.0.0.0.0.0", "₹₹₹", "..!!??", "\x00\x01"):
        assert isinstance(normalizer.normalize(hostile), str)


def test_explain_reports_every_stage():
    """The diagnostic that turns "it mispronounced something" from a guess
    into a two-second answer."""
    trace = OutputNormalizer().explain("**67.4** posts")
    assert trace[0][0] == "input"
    assert any("sixty-seven" in text for _stage, text in trace)


# --- local synthesisers ----------------------------------------------------
#
# The two offline voices exist so a police deployment that loses its internet,
# its Groq key or its budget still has an assistant that talks. What is tested
# here is the wiring around them — selection, language routing, cancellation —
# and not synthesis quality, because loading 310 MB of ONNX weights in a unit
# test would put a half-minute on every run of this file.

def test_a_missing_local_model_is_skipped_rather_than_raising(monkeypatch):
    """The ladder must survive a machine where nobody ran the bootstrap.

    An unprepared box is the normal state of a fresh checkout, and the correct
    outcome is a browser voice, not a stack trace on the officer's first
    question."""
    monkeypatch.setattr(tts.KokoroTTS, "available", staticmethod(lambda: False))
    monkeypatch.setattr(tts.PiperHttpTTS, "available", staticmethod(lambda: False))
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")
    assert tts.resolve() == "browser"
    assert isinstance(tts.create(lambda p: None), tts.BrowserTTS)


def test_a_pinned_local_voice_beats_a_cloud_key(monkeypatch):
    """`VOICE_TTS_PROVIDER=kokoro` is how an air-gapped site says "local, and I
    mean it". A quality ladder that overrode it with whatever key happened to
    be in .env would send audio off-site from a deployment that had explicitly
    asked for the opposite."""
    monkeypatch.setattr(tts.KokoroTTS, "available", staticmethod(lambda: True))
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "sk-live")
    monkeypatch.setattr(settings, "VOICE_TTS_PROVIDER", "kokoro")
    assert tts.resolve() == "kokoro"


def test_the_local_voice_follows_the_language(monkeypatch):
    """An American voice reading Devanagari is unintelligible, so the voice is
    chosen from the language rather than fixed. Gujarati routes to the Hindi
    voice deliberately: Kokoro has no Gujarati, and Hindi shares most of its
    phoneme inventory — far closer than reading it as English letters."""
    monkeypatch.setattr(settings, "KOKORO_VOICE", "")
    english = tts.KokoroTTS(lambda p: None, language="en-IN")
    hindi = tts.KokoroTTS(lambda p: None, language="hi-IN")
    gujarati = tts.KokoroTTS(lambda p: None, language="gu-IN")
    assert (english.lang, english.voice) == ("en-us", tts.KokoroTTS.DEFAULT_VOICE)
    assert (hindi.lang, hindi.voice) == ("hi", tts.KokoroTTS.HINDI_VOICE)
    assert (gujarati.lang, gujarati.voice) == ("hi", tts.KokoroTTS.HINDI_VOICE)


def test_an_unknown_or_auto_language_speaks_english(monkeypatch):
    """`auto` means the recogniser decides per utterance and nothing is known
    at construction time. A Gujarat control room's working language is English
    even when the posts it reads are not."""
    monkeypatch.setattr(settings, "KOKORO_VOICE", "")
    for language in ("auto", "", "sv-SE"):
        assert tts.KokoroTTS(lambda p: None, language=language).lang == "en-us"


def test_an_explicit_voice_overrides_the_language_default(monkeypatch):
    monkeypatch.setattr(settings, "KOKORO_VOICE", "")
    assert tts.KokoroTTS(lambda p: None, voice="am_michael").voice == "am_michael"
    monkeypatch.setattr(settings, "KOKORO_VOICE", "af_bella")
    assert tts.KokoroTTS(lambda p: None, language="hi-IN").voice == "af_bella"


def test_an_interruption_stops_the_local_voice_mid_sentence(monkeypatch):
    """Barge-in is the difference between an assistant and a recording.

    Kokoro generates a whole phoneme batch before any of it is playable, so
    cancellation cannot wait for synthesis to finish — it is checked per
    emitted slice, which is what stops the voice within about a tenth of a
    second of the officer talking over it."""
    emitted: list[bytes] = []

    async def on_packet(packet):
        emitted.append(packet.audio)
        if len(emitted) == 2:            # the officer starts talking
            await speaker.interrupt("ctx")

    class FakeModel:
        def create_stream(self, text, voice, speed, lang):
            async def gen():
                # One second of audio at Kokoro's native rate, in two batches.
                yield np.zeros(24_000, dtype=np.float32), 24_000
                yield np.zeros(24_000, dtype=np.float32), 24_000
            return gen()

    monkeypatch.setattr(tts.KokoroTTS, "_model", FakeModel())
    speaker = tts.KokoroTTS(on_packet, language="en-IN")
    asyncio.run(speaker.speak(TextToSpeechTextPacket(context_id="ctx", text="Surat is quiet.")))

    # Two slices went out and then it stopped: not the ~10 a full second of
    # audio would be, and no is_final, because the turn was abandoned.
    assert len(emitted) == 2
    assert all(len(chunk) <= tts.LOCAL_CHUNK_BYTES for chunk in emitted)


def test_piper_is_offline_until_a_server_is_configured(monkeypatch):
    """Piper is reached over HTTP rather than imported on purpose: the
    `piper-tts` library is GPL-3.0 and importing it would place this backend
    under the GPL's source-disclosure terms. No URL therefore means no Piper —
    there is no in-process path to fall back to."""
    monkeypatch.setattr(settings, "PIPER_HTTP_URL", "")
    assert not tts.PiperHttpTTS.available()
    monkeypatch.setattr(settings, "PIPER_HTTP_URL", "http://127.0.0.1:5000")
    assert tts.PiperHttpTTS.available()


def test_warm_up_is_skipped_when_the_local_voice_will_not_be_used(monkeypatch):
    """310 MB of weights loaded at boot on a box that will always answer
    through ElevenLabs is pure waste."""
    loaded: list[str] = []
    monkeypatch.setattr(tts.KokoroTTS, "load",
                        classmethod(lambda cls: loaded.append("load")))
    monkeypatch.setattr(settings, "VOICE_TTS_PROVIDER", "elevenlabs")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "sk-live")
    tts.warm_local_voice()
    assert loaded == []
