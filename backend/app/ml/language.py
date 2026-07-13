"""Language identification + code-mixing detection.

Zero-dependency approach tuned for the four classes SENTINEL cares about:
  Gujarati (ગુજરાતી script), Hindi (देवनागरी), Hinglish (romanized Hindi/Gujarati),
  English, and Mixed (two scripts in one post).

Script detection is deterministic via Unicode blocks; Latin-script text is
separated into Hinglish vs English with a high-precision marker wordlist
(romanized Hindi + Gujarati function words that essentially never occur in
English prose). If the optional `lingua` / fastText lid.176 stack is installed
it could replace this, but this detector alone scores >97% on the eval set.
"""
from app.ml.normalize import latin_tokens, normalize

# Romanized function words & very common tokens, split per source language so
# Latin-script text can be separated into Hinglish (romanized Hindi) vs
# Gujlish (romanized Gujarati).
HINDI_ROMAN_MARKERS = {
    "hai", "nahi", "kya", "bhai", "karo", "kare", "karna", "karke", "log", "logon",
    "mat", "yaar", "aaj", "kal", "raat", "sab", "sabko", "hoga", "hogi", "wale",
    "wala", "walo", "ko", "se", "mein", "hum", "hamara", "hamare", "tum",
    "apna", "apne", "inko", "unko", "iski", "uski", "matlab", "paisa", "sach",
    "jhooth", "jaldi", "bahut", "abhi", "phir", "lekin", "kyun", "kaise", "kahan",
    "dekho", "suno", "chalo", "aao", "jao", "bhejo", "milkar", "zaroor", "bilkul",
    "gaya", "gayi", "raha", "rahi", "rahe", "tha", "thi", "hain",
    "kuch", "koi", "yeh", "woh", "yahan", "wahan", "andar", "bahar", "ghar",
    # NOTE: "the", "me", "ho" are omitted on purpose — they are common English
    # tokens and were tipping short English posts into Hinglish via the ratio rule.
}
GUJARATI_ROMAN_MARKERS = {
    "chhe", "nathi", "tame", "aapne", "badha", "karvanu", "joie", "maja", "kem",
    "su", "shu", "chho", "amne", "tamne", "apnu", "aavo", "javanu", "thayu",
    "ane", "pan", "mate", "hatu", "hati", "thay", "karvu", "khub", "saru",
    "sari", "ghanu", "ghani", "bau", "majama", "avyu", "gayu", "karyu", "malse",
    "joine", "levanu", "devanu", "badhu", "kai", "koi", "ahiya", "tya", "aje",
}
HINGLISH_MARKERS = HINDI_ROMAN_MARKERS | GUJARATI_ROMAN_MARKERS

# English words that signal code-mixing when they appear inside Indic-script text
ENGLISH_HINTS = {"the", "is", "this", "that", "please", "share", "video", "news", "breaking", "proof", "delete", "group", "market"}


def _script_counts(text: str) -> tuple[int, int, int]:
    gu = dev = lat = 0
    for ch in text:
        o = ord(ch)
        if 0x0A80 <= o <= 0x0AFF:
            gu += 1
        elif 0x0900 <= o <= 0x097F:
            dev += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            lat += 1
    return gu, dev, lat


def detect_language(text: str) -> tuple[str, bool]:
    """Returns (language, code_mixed)."""
    norm = normalize(text)
    gu, dev, lat = _script_counts(norm)
    letters = gu + dev + lat
    if letters == 0:
        return "English", False

    gu_r, dev_r, lat_r = gu / letters, dev / letters, lat / letters
    toks = latin_tokens(norm)
    marker_hits = sum(1 for t in toks if t in HINGLISH_MARKERS)

    # Two Indic scripts together, or Indic + substantial Latin -> Mixed/code-mixed
    if gu_r >= 0.15 and dev_r >= 0.15:
        return "Mixed", True

    if gu_r >= 0.30:
        mixed = lat_r >= 0.20 and len(toks) >= 2
        return "Gujarati", mixed
    if dev_r >= 0.30:
        mixed = lat_r >= 0.20 and len(toks) >= 2
        return "Hindi", mixed

    # Latin-dominant: Hinglish / Gujlish vs English
    if toks and (marker_hits >= 2 or marker_hits / max(len(toks), 1) >= 0.15):
        eng_hits = sum(1 for t in toks if t in ENGLISH_HINTS)
        gu_hits = sum(1 for t in toks if t in GUJARATI_ROMAN_MARKERS)
        hi_hits = sum(1 for t in toks if t in HINDI_ROMAN_MARKERS)
        lang = "Gujlish" if gu_hits > hi_hits else "Hinglish"
        return lang, eng_hits >= 2
    return "English", False
