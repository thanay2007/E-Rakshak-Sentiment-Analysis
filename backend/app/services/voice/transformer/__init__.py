"""Provider adapters for speech recognition and synthesis.

Mirrors Rapida's `internal/transformer/`: one factory per direction, providers
selected by name, and every provider behind the same interface so the session
never learns which one it got.
"""
from app.services.voice.transformer import stt, tts  # noqa: F401
from app.services.voice.transformer.base import (MIN_UTTERANCE_MS,  # noqa: F401
                                                 SpeechToText, TextToSpeech)

__all__ = ["stt", "tts", "SpeechToText", "TextToSpeech", "MIN_UTTERANCE_MS"]
