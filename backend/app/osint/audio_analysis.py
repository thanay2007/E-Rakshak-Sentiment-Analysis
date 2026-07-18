import logging
import whisper
import os

log = logging.getLogger("sentinel.osint.audio")

# Load base model globally so it's ready. In production, consider lazy loading or a separate worker.
_model = None

def get_whisper_model():
    global _model
    if _model is None:
        log.info("Loading Whisper base model for offline transcription...")
        _model = whisper.load_model("base")
    return _model

def transcribe_audio(file_path: str) -> dict:
    """Uses offline Whisper to transcribe an audio/video file."""
    if not os.path.exists(file_path):
        return {"error": "File not found"}
        
    try:
        model = get_whisper_model()
        result = model.transcribe(file_path)
        return {
            "text": result["text"].strip(),
            "language": result.get("language", "unknown"),
        }
    except Exception as e:
        log.error(f"Whisper transcription failed: {e}")
        return {"error": str(e)}
