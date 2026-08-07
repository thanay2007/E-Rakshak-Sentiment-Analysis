"""URLs, handles, symbols and markdown — everything that is written, not said.

Ports Rapida's `url_normalizer.go`, `symbol_normalizer.go`,
`address_normalizer.go` and the markdown/emoji stripping at the top of
`normalizer.go`.

These share one job: removing things that exist only because text is looked at.
A URL read aloud character by character is thirty seconds of noise. A markdown
asterisk becomes the spoken word "asterisk" on some engines and a stumble on
others. An emoji becomes either silence or, on a few engines, its CLDR name —
"grinning face with smiling eyes" — in the middle of a threat briefing.

The handle rule is the one with a real decision behind it. `@SantaniSubhajit`
is read "at Santani Subhajit", with the camel case split into words, because
the alternative is a synthesiser attempting the whole run-together string as a
single word and producing something unintelligible. Underscores and digits get
the same treatment. This is the form an officer can actually write down.
"""
from __future__ import annotations

import re

# ── markdown, from Rapida's normalizer.go ───────────────────────────────────

_MD_BLOCK = re.compile(r"```[^`]*```", re.DOTALL)
_MD_INLINE = re.compile(r"`([^`]+)`")
_MD_HEADING = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_EMPH = re.compile(r"\*{1,2}([^*]+?)\*{1,2}|_{1,2}([^_]+?)_{1,2}")
_MD_QUOTE = re.compile(r"^>\s?", re.MULTILINE)
_MD_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})$", re.MULTILINE)
_MD_STARS = re.compile(r"[*]+")
_WORD_UNDERSCORE = re.compile(r"(\w)_(\w)")

_EMOJI = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF☀-⛿✀-➿︀-️"
    "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
    "‍⃣]+")

_WHITESPACE = re.compile(r"\s+")


class MarkdownNormalizer:
    """Strips formatting a model emitted despite being told not to."""

    name = "markdown"

    def normalize(self, text: str) -> str:
        text = _MD_BLOCK.sub(" ", text)
        text = _MD_INLINE.sub(r"\1", text)
        text = _MD_HEADING.sub("", text)
        text = _MD_IMAGE.sub("", text)
        # Keep the link text, drop the target — the words carry the meaning.
        text = _MD_LINK.sub(r"\1", text)
        text = _MD_EMPH.sub(lambda m: m.group(1) or m.group(2) or "", text)
        text = _MD_QUOTE.sub("", text)
        text = _MD_HR.sub("", text)
        text = _MD_STARS.sub("", text)
        text = _WORD_UNDERSCORE.sub(r"\1 \2", text)
        text = _EMOJI.sub("", text)
        return _WHITESPACE.sub(" ", text).strip()


# ── URLs and handles ────────────────────────────────────────────────────────

_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_HANDLE = re.compile(r"@([A-Za-z0-9_]{2,30})\b")
_HASHTAG = re.compile(r"#([A-Za-z0-9_]{2,40})\b")

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")

_KNOWN_DOMAINS = {
    "twitter.com": "Twitter", "x.com": "X", "reddit.com": "Reddit",
    "facebook.com": "Facebook", "instagram.com": "Instagram",
    "youtube.com": "YouTube", "youtu.be": "YouTube", "t.me": "Telegram",
}


def split_identifier(raw: str) -> str:
    """`SantaniSubhajit_01` → `Santani Subhajit 01`.

    Camel case, underscores and letter/digit transitions all become word
    boundaries. Without this a synthesiser meets one 18-character token and
    guesses.
    """
    spaced = raw.replace("_", " ").replace("-", " ")
    return _WHITESPACE.sub(" ", _CAMEL.sub(" ", spaced)).strip()


class UrlNormalizer:
    """Replaces addresses with a description of where they point."""

    name = "url"

    def normalize(self, text: str) -> str:
        def _url(match: re.Match) -> str:
            address = match.group(0)
            host = re.sub(r"^https?://", "", address, flags=re.IGNORECASE)
            host = host.split("/")[0].lower().removeprefix("www.")
            known = _KNOWN_DOMAINS.get(host)
            return f"a link to {known}" if known else "a link"

        def _email(match: re.Match) -> str:
            # Spelling out a full address is unusable in audio. The local part
            # is enough for the officer to know whose it is.
            local = match.group(0).split("@")[0]
            return f"an email address for {split_identifier(local)}"

        text = _URL.sub(_url, text)
        text = _EMAIL.sub(_email, text)
        text = _HANDLE.sub(lambda m: f"at {split_identifier(m.group(1))}", text)
        text = _HASHTAG.sub(
            lambda m: f"hashtag {split_identifier(m.group(1))}", text)
        return text


# ── residual symbols ────────────────────────────────────────────────────────

_SYMBOLS: dict[str, str] = {
    # An arrow in this product is almost always a UI path — "Admin Panel →
    # Officers" — and "Admin Panel to Officers" is not how anyone says that
    # out loud. "then" reads as the navigation step it actually is.
    "→": " then ", "←": " from ", "↑": " up ", "↓": " down ",
    "≥": " at least ", "≤": " at most ", "≠": " not equal to ",
    "<": " less than ", ">": " greater than ",
    "±": " plus or minus ", "×": " times ", "÷": " divided by ",
    "°": " degrees ", "™": "", "®": "", "©": "",
    "–": " ", "—": " ", "…": " ", "•": " ", "|": " ", "/": " or ",
    " ": " ",
}

_REPEATED_PUNCT = re.compile(r"([,.!?;:])\1+")
_ORPHANED = re.compile(r"\s+([,.!?;:])")
# Spelling a number produces a lower-case word, so "0 posts scored" at the
# start of a sentence becomes "zero posts scored". Invisible to a synthesiser
# but wrong on screen, and the transcript is read as often as it is heard.
_SENTENCE_START = re.compile(r"(^|[.!?।۔]\s+)([a-z])")


class SymbolNormalizer:
    """Last pass: whatever is left that has no pronunciation."""

    name = "symbol"

    def normalize(self, text: str) -> str:
        for symbol, spoken in _SYMBOLS.items():
            text = text.replace(symbol, spoken)
        # Brackets are silent, but their contents are not — drop the marks and
        # keep the words, or a parenthetical is lost entirely.
        text = re.sub(r"[()\[\]{}\"]", " ", text)
        text = _REPEATED_PUNCT.sub(r"\1", text)
        text = _ORPHANED.sub(r"\1", text)
        text = _WHITESPACE.sub(" ", text).strip()
        return _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)
