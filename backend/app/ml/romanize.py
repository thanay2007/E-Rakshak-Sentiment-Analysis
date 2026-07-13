# -*- coding: utf-8 -*-
"""Deterministic Indic → Latin romanizer (Devanagari + Gujarati).

Feature ported from anoopkunchukuttan/indic_nlp_library (transliteration
module), re-tuned for SOCIAL-MEDIA style output: instead of scholarly ITRANS
("nahIM", "Che") it produces the colloquial spellings people actually type
("nahi", "chhe"), so romanized rows read like real Hinglish/Gujlish posts.

Used by download_datasets.py to synthesize Gujlish/Hinglish training rows
from native-script Gujarati/Hindi corpora (standard augmentation for
zero-resource code-mixed languages). If indic-nlp-library is installed its
canonical script normalizer runs first (nukta/matra unicode variants).

Both scripts share the same Brahmi block layout, so one offset table covers
Devanagari (U+0900) and Gujarati (U+0A80).
"""
from __future__ import annotations

DEV_BASE = 0x0900
GUJ_BASE = 0x0A80

# offset-from-block-start -> latin. Consonants carry an implicit "a".
_VOWELS = {
    0x05: "a", 0x06: "a", 0x07: "i", 0x08: "i", 0x09: "u", 0x0A: "u",
    0x0B: "ri", 0x0D: "e", 0x0E: "e", 0x0F: "e", 0x10: "ai",
    0x11: "o", 0x12: "o", 0x13: "o", 0x14: "au",
}
_CONSONANTS = {
    0x15: "k", 0x16: "kh", 0x17: "g", 0x18: "gh", 0x19: "n",
    0x1A: "ch", 0x1B: "chh", 0x1C: "j", 0x1D: "jh", 0x1E: "n",
    0x1F: "t", 0x20: "th", 0x21: "d", 0x22: "dh", 0x23: "n",
    0x24: "t", 0x25: "th", 0x26: "d", 0x27: "dh", 0x28: "n", 0x29: "n",
    0x2A: "p", 0x2B: "f", 0x2C: "b", 0x2D: "bh", 0x2E: "m",
    0x2F: "y", 0x30: "r", 0x31: "r", 0x32: "l", 0x33: "l", 0x34: "l",
    0x35: "v", 0x36: "sh", 0x37: "sh", 0x38: "s", 0x39: "h",
}
_MATRAS = {
    0x3E: "a", 0x3F: "i", 0x40: "i", 0x41: "u", 0x42: "u", 0x43: "ru",
    0x45: "e", 0x46: "e", 0x47: "e", 0x48: "ai",
    0x49: "o", 0x4A: "o", 0x4B: "o", 0x4C: "au",
}
_VIRAMA = 0x4D
_ANUSVARA = {0x01, 0x02}   # candrabindu + anusvara
_VISARGA = 0x03
_NUKTA = 0x3C
_LABIALS = {"p", "f", "b", "bh", "m"}
# nukta consonant remaps (Hindi loan sounds): जज़ -> z, फ़ -> f
_NUKTA_MAP = {"j": "z", "f": "f", "kh": "kh", "g": "g", "d": "d", "dh": "dh", "k": "q"}

# High-frequency function words people spell idiosyncratically — a small
# override lexicon keeps the synthesized text indistinguishable from typed
# Hinglish/Gujlish where it matters most.
OVERRIDES = {
    # Hindi
    "है": "hai", "हैं": "hain", "में": "mein", "नहीं": "nahi", "मैं": "main",
    "और": "aur", "क्या": "kya", "क्यों": "kyun", "कोई": "koi", "यह": "yeh",
    "वह": "woh", "हूँ": "hoon", "हूं": "hoon", "थे": "the", "बहुत": "bahut",
    "कुछ": "kuch", "अच्छा": "accha", "अच्छी": "acchi", "अच्छे": "acche",
    "पर": "par", "भी": "bhi", "तो": "toh", "हो": "ho", "गया": "gaya",
    "गयी": "gayi", "गई": "gayi", "रहा": "raha", "रही": "rahi", "रहे": "rahe",
    "करना": "karna", "किया": "kiya", "लिए": "liye", "साथ": "saath",
    # Gujarati
    "છે": "chhe", "છો": "chho", "નથી": "nathi", "તમે": "tame", "અને": "ane",
    "શું": "shu", "કેમ": "kem", "હું": "hu", "તું": "tu", "આ": "aa",
    "તે": "te", "પણ": "pan", "માટે": "mate", "હતું": "hatu", "હતી": "hati",
    "થાય": "thay", "કરવું": "karvu", "ખૂબ": "khub", "સારું": "saru",
    "સારી": "sari", "જ": "j", "થી": "thi", "ના": "na", "નું": "nu",
}


def _block_offset(ch: str) -> int | None:
    o = ord(ch)
    if 0x0900 <= o <= 0x097F:
        return o - DEV_BASE
    if 0x0A80 <= o <= 0x0AFF:
        return o - GUJ_BASE
    return None


def _romanize_word(word: str) -> str:
    """One Indic-script word -> colloquial Latin syllable string."""
    if word in OVERRIDES:
        return OVERRIDES[word]
    sylls: list[str] = []          # each syllable: consonant(s) + vowel
    pending: str | None = None     # consonant awaiting its vowel
    for i, ch in enumerate(word):
        off = _block_offset(ch)
        if off is None:
            if pending is not None:
                sylls.append(pending + "a")
                pending = None
            sylls.append(ch)
            continue
        if off in _CONSONANTS:
            if pending is not None:
                sylls.append(pending + "a")   # inherent vowel of previous
            pending = _CONSONANTS[off]
        elif off == _NUKTA:
            if pending in _NUKTA_MAP:
                pending = _NUKTA_MAP[pending]
        elif off in _MATRAS:
            sylls.append((pending or "") + _MATRAS[off])
            pending = None
        elif off == _VIRAMA:
            if pending is not None:
                sylls.append(pending)         # bare consonant (cluster)
                pending = None
        elif off in _VOWELS:
            if pending is not None:
                sylls.append(pending + "a")
                pending = None
            sylls.append(_VOWELS[off])
        elif off in _ANUSVARA:
            if pending is not None:
                sylls.append(pending + "a")
                pending = None
            nxt = _block_offset(word[i + 1]) if i + 1 < len(word) else None
            nasal = "m" if nxt in _CONSONANTS and _CONSONANTS[nxt] in _LABIALS else "n"
            if sylls:
                sylls[-1] += nasal
            else:
                sylls.append(nasal)
        elif off == _VISARGA:
            if sylls:
                sylls[-1] += "h"
        elif 0x66 <= off <= 0x6F:
            if pending is not None:
                sylls.append(pending + "a")
                pending = None
            sylls.append(str(off - 0x66))
        # danda / candrabindu variants / rare signs: drop
    if pending is not None:
        # word-final consonant: schwa deletion ("samay", not "samaya")
        sylls.append(pending if sylls else pending + "a")

    # penultimate schwa deletion: ka|ra|na -> kar|na ("karna", "photoshoot"-era
    # colloquial Hinglish drops the middle inherent vowel before a final
    # explicit-vowel syllable)
    if len(sylls) >= 3 and sylls[-2].endswith("a") and len(sylls[-2]) >= 2 \
            and any(v in sylls[-1] for v in "aeiou") and not sylls[-1][:1].isdigit():
        body = sylls[-2][:-1]
        if body in _CONSONANTS.values() or body in _NUKTA_MAP.values():
            sylls[-2] = body
    return "".join(sylls)


def romanize(text: str) -> str:
    """Romanize every Indic-script run in `text`; Latin/emoji pass through."""
    try:  # indic-nlp canonical normalization first, when available
        from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
        for code, lo, hi in (("hi", 0x0900, 0x097F), ("gu", 0x0A80, 0x0AFF)):
            if any(lo <= ord(c) <= hi for c in text):
                text = IndicNormalizerFactory().get_normalizer(code).normalize(text)
    except Exception:
        pass

    out: list[str] = []
    word: list[str] = []
    for ch in text:
        if _block_offset(ch) is not None:
            word.append(ch)
        else:
            if word:
                out.append(_romanize_word("".join(word)))
                word = []
            out.append(ch)
    if word:
        out.append(_romanize_word("".join(word)))
    return "".join(out)


if __name__ == "__main__":
    for s in ["ये सरकार बहुत अच्छा काम कर रही है",
              "આ ફિલ્મ ખૂબ સારી છે અને વાર્તા પણ મજબૂત છે",
              "मैं नहीं जाऊंगा क्योंकि बारिश हो रही है"]:
        print(s, "->", romanize(s))
