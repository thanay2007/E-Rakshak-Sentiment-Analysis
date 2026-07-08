"""Lite multilingual sentiment: valence lexicons + emoji signal.
Replaced by cardiffnlp/twitter-xlm-roberta-base-sentiment in full mode."""
from app.ml import lexicons as lx
from app.ml.matcher import match_terms, score
from app.ml.normalize import normalize


def analyze_sentiment(text: str, threat_signals: dict | None = None) -> tuple[str, float]:
    """Returns (label, score) with score in [-1, +1]."""
    norm = normalize(text)
    pos = score(match_terms(norm, lx.POSITIVE))
    neg = score(match_terms(norm, lx.NEGATIVE))

    # Threat language is intrinsically negative even without valence words
    if threat_signals:
        neg += 0.9 * threat_signals.get("violence", 0)
        neg += 0.7 * threat_signals.get("hostility", 0)
        neg += 0.5 * threat_signals.get("abuse", 0)
        neg += 0.3 * threat_signals.get("fake_markers", 0)

    pos += 0.3 * sum(1 for ch in text if ch in lx.POSITIVE_EMOJI)
    neg += 0.3 * sum(1 for ch in text if ch in lx.NEGATIVE_EMOJI)

    value = (pos - neg) / (pos + neg + 0.8)  # smoothed, bounded (-1, 1)
    value = max(-1.0, min(1.0, value))
    if value > 0.12:
        label = "positive"
    elif value < -0.12:
        label = "negative"
    else:
        label = "neutral"
    return label, round(value, 3)
