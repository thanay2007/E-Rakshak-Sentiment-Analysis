"""Abbreviations → what they are actually called out loud.

Ports three of Rapida's normalizers into one module, because they differ only
in their dictionary:

    general_abbreviation_normalizer.go   e.g., i.e., approx, etc
    role_abbreviation_normalizer.go      job titles — replaced wholesale with
                                         the Indian police rank structure
    tech_abbreviation_normalizer.go      API, URL, ID, and this product's own

The rank table is the reason this module matters more here than it does in
Rapida. An assistant used by Gujarat Police says "DCP", "SHO", "FIR" and "IPC"
constantly, and a synthesiser given "DCP" will say "duh-sip" or spell it as
three letters with no pause — either of which sounds like the tool does not
know what it is talking about.

Three-way handling, because not every abbreviation wants the same treatment:

    EXPANDED    written out in full        SHO → Station House Officer
    SPELLED     read letter by letter      IPS → I P S
    KEPT        left exactly as written    FIR → FIR

The distinction is not stylistic. `FIR` is *said* "eff eye arr" by every police
officer in India and expanding it to "First Information Report" mid-sentence
would be the odd thing to do. `SHO` is said in full. Which is which is
knowledge about the domain, not about text.
"""
from __future__ import annotations

import re

# Written out in full.
EXPANDED: dict[str, str] = {
    # police ranks and units
    "sho": "Station House Officer",
    "asi": "Assistant Sub Inspector",
    "psi": "Police Sub Inspector",
    "si": "Sub Inspector",
    "insp": "Inspector",
    "dysp": "Deputy Superintendent of Police",
    "dsp": "Deputy Superintendent of Police",
    "sp": "Superintendent of Police",
    "ssp": "Senior Superintendent of Police",
    "acp": "Assistant Commissioner of Police",
    "dcp": "Deputy Commissioner of Police",
    "jcp": "Joint Commissioner of Police",
    "addl": "Additional",
    "cp": "Commissioner of Police",
    "dgp": "Director General of Police",
    "adgp": "Additional Director General of Police",
    "igp": "Inspector General of Police",
    "ps": "police station",
    "pcr": "Police Control Room",
    "sog": "Special Operations Group",
    "ats": "Anti Terrorism Squad",
    # general
    "approx": "approximately",
    "etc": "et cetera",
    "vs": "versus",
    "viz": "namely",
    "dept": "department",
    "govt": "government",
    "no": "number",
    "nos": "numbers",
    "min": "minimum",
    "max": "maximum",
    "avg": "average",
    "info": "information",
    "msg": "message",
    "pls": "please",
    "asap": "as soon as possible",
    # this product
    "osint": "open source intelligence",
    "nlp": "natural language processing",
    "ml": "machine learning",
    "vad": "voice activity detection",
    "stt": "speech to text",
    "tts": "text to speech",
    "nic": "National Informatics Centre",
}

# Read letter by letter. Spaces between the letters stop a synthesiser trying
# to pronounce the sequence as a word.
SPELLED: frozenset[str] = frozenset({
    "fir", "ipc", "crpc", "ips", "ias", "cid", "cbi", "nia", "ncb",
    "api", "url", "id", "ui", "ux", "sql", "json", "csv", "pdf", "http",
    "https", "gps", "sim", "imei", "ip", "otp", "kyc", "cctv", "sms",
    "llm", "gpu", "cpu", "ram", "rbac", "jwt", "ssrf",
})

# Left alone: already pronounceable as words.
KEPT: frozenset[str] = frozenset({
    "sentinel", "muril", "bert", "vader", "groq", "reddit", "whatsapp",
    "unicode", "radar", "laser", "nasa", "covid", "aids",
})

_PHRASES: dict[str, str] = {
    "e.g.": "for example",
    "eg.": "for example",
    "i.e.": "that is",
    "ie.": "that is",
    "a.k.a.": "also known as",
    "w.r.t.": "with respect to",
    "24x7": "twenty four seven",
    "24/7": "twenty four seven",
    "&": "and",
    "@": "at",
    "%": "percent",
    "#": "number",
    "+": "plus",
    "=": "equals",
}

_WORD = re.compile(r"\b[A-Za-z][A-Za-z.]*\b")


def _spell_out(token: str) -> str:
    return " ".join(token.upper())


class AbbreviationNormalizer:
    """One pass over the sentence, checking each word against the tables.

    Case-sensitivity is the subtlety. `SP` is a rank; `sp` in lower case is
    almost certainly part of a word or a typo, and expanding it produces
    nonsense. So the rank and spelled tables only fire on a token that was
    written in upper case, while the general abbreviations fire in any case
    because "approx" is never capitalised.
    """

    name = "abbreviation"

    # Expanding these on a lower-case token would corrupt ordinary prose.
    _UPPER_ONLY = frozenset({"sp", "si", "ps", "cp", "ml", "no", "nos",
                             "id", "ip", "min", "max"})

    def normalize(self, text: str) -> str:
        for phrase, spoken in _PHRASES.items():
            text = re.sub(re.escape(phrase), f" {spoken} ", text,
                          flags=re.IGNORECASE)

        def _replace(match: re.Match) -> str:
            token = match.group(0)
            key = token.rstrip(".").lower()
            if not key or key in KEPT:
                return token
            was_upper = token.rstrip(".").isupper()
            if key in self._UPPER_ONLY and not was_upper:
                return token
            if key in SPELLED:
                return _spell_out(key) if was_upper or len(key) <= 4 else token
            if key in EXPANDED:
                return EXPANDED[key]
            # An unknown all-caps run of 2-5 letters is an acronym nobody
            # taught us. Spelling it is always intelligible; guessing at a
            # pronunciation is not.
            if was_upper and 2 <= len(key) <= 5 and key.isalpha():
                return _spell_out(key)
            return token

        return re.sub(r"\s{2,}", " ", _WORD.sub(_replace, text)).strip()
