"""Lite toxicity / hate-speech flagging with code-mixing support.
Replaced by a multilingual toxic-XLM-R classifier in full mode."""


def analyze_toxicity(signals: dict) -> tuple[float, list[str]]:
    """Derive a 0..1 toxicity score + human-readable flags from classifier signals."""
    flags: list[str] = []
    tox = 0.0

    if signals.get("abuse", 0) > 0.3:
        flags.append("abusive_language")
        tox += min(0.35, signals["abuse"] * 0.35)
    if signals.get("hostility", 0) > 0.4:
        flags.append("targeted_hate")
        tox += min(0.30, signals["hostility"] * 0.25)
    if signals.get("violence", 0) > 0.4:
        flags.append("call_to_violence")
        tox += min(0.40, signals["violence"] * 0.35)
    if signals.get("mobilization"):
        flags.append("mobilization")
        tox += 0.15
    if signals.get("targets_official"):
        flags.append("targets_official")
        tox += 0.15

    return round(min(1.0, tox), 3), flags
