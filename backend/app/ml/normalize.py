"""Text normalization before NLP.

Handles the messiness of Indian social media text: URLs, @mentions, stretched
characters ("bhaiiii"), and common romanized-Hindi/Gujarati spelling variants
("nhi" -> "nahi") so the lexicon matchers and language detector see canonical
forms. Runs before every lite-mode component and before transformer tokenizers.
"""
import re

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@[\w_]+")
_REPEAT_RE = re.compile(r"(.)\1{2,}")
_MULTISPACE_RE = re.compile(r"\s+")

# Romanized slang / transliteration variants -> canonical romanized form.
# Applied token-wise on Latin-script tokens only.
SLANG_MAP = {
    "nhi": "nahi", "nai": "nahi", "nahin": "nahi", "ni": "nahi",
    "kro": "karo", "kr": "kar", "krna": "karna", "krte": "karte",
    "jldi": "jaldi", "bhut": "bahut", "bht": "bahut", "bohot": "bahut",
    "sb": "sab", "sbko": "sabko", "mt": "mat", "h": "hai", "hy": "hai",
    "kyu": "kyun", "q": "kyun", "plz": "please", "pls": "please",
    "shr": "share", "fwd": "forward", "msg": "message",
    "aajao": "aa jao", "ajao": "aa jao", "chalo": "chalo",
    "mrna": "marna", "maro": "maaro", "jla": "jala", "jlado": "jala do",
    "khtm": "khatam", "khatm": "khatam", "bdla": "badla",
    "che": "chhe", " 6e": " chhe", "nthi": "nathi",
}

_TOKEN_RE = re.compile(r"[a-z]+", re.IGNORECASE)


def normalize(text: str) -> str:
    """Return a canonical string for matching: no URLs/mentions, collapsed
    stretch-chars, lowercased Latin, slang-normalized romanized tokens."""
    t = _URL_RE.sub(" ", text)
    t = _MENTION_RE.sub(" ", t)
    t = _REPEAT_RE.sub(r"\1\1", t)  # "bhaiiii" -> "bhaii"

    def _fix(m: re.Match) -> str:
        tok = m.group(0).lower()
        return SLANG_MAP.get(tok, tok)

    t = _TOKEN_RE.sub(_fix, t)
    t = _MULTISPACE_RE.sub(" ", t).strip()
    return t


def latin_tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]
