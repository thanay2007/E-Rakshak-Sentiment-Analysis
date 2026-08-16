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
from app.ml.normalize import SLANG_MAP, latin_tokens, normalize

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

# Distinctly-Filipino (Tagalog/Taglish) function words. Real crawled feeds
# occasionally surface Filipino posts, and shared tokens ("wala", "ko", "na")
# were tipping them into Hinglish. The check exists only as a VETO on the
# Hinglish call — matching posts are labeled plain English (slang/typos in
# Latin script are never assumed to be another language).
FILIPINO_MARKERS = {
    "ang", "mga", "ako", "ikaw", "siya", "kami", "kayo", "sila", "ito", "iyan",
    "po", "opo", "naman", "nman", "lang", "nlang", "kasi", "kase", "pag", "kapag",
    "talaga", "gusto", "dito", "doon", "meron", "wala", "walang", "ganito",
    "ganyan", "salamat", "natin", "namin", "akin", "iyo", "kanya", "iwan",
    "hanggang", "bakit", "paano", "saan", "sino", "kailan", "muna", "pala",
    "daw", "raw", "din", "rin", "yung", "yan", "yun", "niya", "nila", "natin",
    "kang", "kong", "mong", "nga", "ba", "eh", "charot", "charing", "grabe",
}

# tokens Filipino shares with Hindi/Gujarati marker lists — excluded from the
# Hinglish tally when the post looks Filipino overall
_AMBIGUOUS = {"wala", "ko", "na", "din", "ba", "aa"}


import re

_REPEAT_RE = re.compile(r"(.)\1{2,}")


def _squeeze(token: str) -> str:
    """Collapse social-media elongation: 'talagaaaaa' -> 'talaga'."""
    return _REPEAT_RE.sub(r"\1", token)


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


#: Scripts this console does not read, and does not pretend to. Anything here
#: is a *label*, never a filter: the post is still collected, still scored and
#: — because the label is not "English" — still queued for an English gloss.
_FOREIGN_RANGES = (
    (0x4E00, 0x9FFF),    # CJK unified ideographs (Chinese, Kanji)
    (0x3040, 0x30FF),    # Hiragana + Katakana
    (0xAC00, 0xD7AF),    # Hangul syllables
    (0x0600, 0x06FF),    # Arabic
    (0x0400, 0x04FF),    # Cyrillic
    (0x0E00, 0x0E7F),    # Thai
    (0x0590, 0x05FF),    # Hebrew
)


def _foreign_count(text: str) -> int:
    """Characters in a script none of the labels above can describe.

    Without this, a wholly Chinese post has zero Gujarati, zero Devanagari and
    zero Latin letters, falls through every ratio test, and is filed as
    *English* — which is how 51 Chinese-language videos ended up in the corpus
    labelled English and were never sent for translation.
    """
    total = 0
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _FOREIGN_RANGES):
            total += 1
    return total


#: A hashtag and its body. Stripped before the script counts are taken.
_HASHTAG_RE = re.compile(r"#\S+")


def _body(text: str) -> str:
    """The post minus its hashtags — what the author actually wrote.

    Hashtags are overwhelmingly Latin even on posts written entirely in
    Gujarati ("...ચપ્પલથી કોઈ બચી શકે? #surticomedy #gujaraticomedy #reels
    #instagram"), and a social-media caption can carry twenty of them. Counted
    as body text they swamp the script ratio, and the post is filed as English:
    on live Instagram data this mislabelled most Gujarati captions, which then
    lose their translation, their code-mixing flag, and any language filter an
    analyst applies. They are already collected separately into `hashtags`, so
    nothing is lost by leaving them out of this judgement.

    A caption that is *only* hashtags keeps them — there is nothing else to
    read, and guessing English for a wall of Gujarati tags would be the same
    mistake in the other direction.
    """
    stripped = _HASHTAG_RE.sub(" ", text)
    return stripped if len(stripped.strip()) >= 5 else text


def detect_language(text: str) -> tuple[str, bool]:
    """Returns (language, code_mixed)."""
    norm = normalize(_body(text))
    gu, dev, lat = _script_counts(norm)
    foreign = _foreign_count(norm)
    letters = gu + dev + lat
    # Judged before the Indic ratios, and against every letter including the
    # foreign ones: a post that is mostly Chinese with an English hashtag is
    # Chinese. Below the threshold it falls through, so one Japanese emoji-word
    # in an English sentence still reads as English.
    if foreign and foreign / max(letters + foreign, 1) >= 0.30:
        return "Other", lat > 0
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

    # Latin-dominant: Hinglish / Gujlish vs English.
    # Social-media elongation ("talagaaaaa") is collapsed before marker lookup.
    # Filipino-looking text is NOT given its own label — it only vetoes the
    # Hinglish call and falls through to English (could be slang or typos).
    squeezed = [_squeeze(t) for t in toks]
    fil_hits = sum(1 for t in squeezed if t in FILIPINO_MARKERS)
    if fil_hits >= 2 and fil_hits > sum(
        1 for t in squeezed if t in HINGLISH_MARKERS and t not in _AMBIGUOUS
    ):
        return "English", False

    if toks and (marker_hits >= 2 or marker_hits / max(len(toks), 1) >= 0.15):
        eng_hits = sum(1 for t in toks if t in ENGLISH_HINTS)
        gu_hits = sum(1 for t in toks if t in GUJARATI_ROMAN_MARKERS)
        hi_hits = sum(1 for t in toks if t in HINDI_ROMAN_MARKERS)
        lang = "Gujlish" if gu_hits > hi_hits else "Hinglish"
        return lang, eng_hits >= 2
    # English *as a label*, but not necessarily English all the way through: a
    # stray Devanagari word or one romanized marker is below every threshold
    # above and yet is exactly the post an officer cannot read. Flag it as
    # code-mixed so it still qualifies for a translation — see has_indic_content.
    return "English", has_indic_content(text)


# Marker tokens that are also ordinary English words ("log the complaint",
# "a hot pan", "my mate"). Two of them together still read as Hinglish and the
# rule above catches that; ONE of them is not evidence of anything, and this is
# the set that would otherwise send every second English post to the translator.
_ENGLISH_COLLISIONS = {
    "log", "mat", "sab", "pan", "mate", "koi", "so", "sari", "san", "hi",
}

# Romanized CONTENT words — the ones that actually carry a grievance when a
# post is otherwise English ("the drainage is kharab", "ward office ne
# complaint kari"). The marker lists above are function words, chosen for
# telling one language from another; these are chosen for the other job, of
# noticing that a translation is owed. Deliberately not exhaustive: no
# wordlist covers a living language, which is why the detail drawer also
# carries a manual Translate control that overrides everything here.
_ROMAN_CONTENT = {
    # verbs / actions
    "kari", "karyo", "karyu", "karta", "karti", "karte", "thayo", "thaya",
    "thase", "aavse", "avse", "jase", "levu", "aapo", "aapvu", "bolo", "bole",
    "kaho", "kehta", "puchho", "lagta", "lagyu", "malyu",
    "banavyu", "banavo", "mokalo", "batao", "bataye", "samjho",
    "samjhe", "rakho", "dedo", "diya", "diye", "liya", "leke",
    # nouns / grievance vocabulary an officer actually meets. English-shaped
    # words a city post is full of anyway ("police", "society", "vote") are
    # deliberately absent — one of those is not evidence of anything.
    "sarkar", "neta", "adhikari", "rasta", "rasto", "pani",
    "bijli", "kachro", "kachra", "gandagi", "pareshani", "takleef",
    "samasya", "fariyad", "arji", "vepari", "dukan", "mandir",
    "masjid", "gaam", "shaher", "vistar", "nagarpalika",
    "mahanagarpalika", "chunav", "bhrashtachar", "ghotala",
    # adjectives / intensity
    "kharab", "saras", "sundar", "mast", "badhiya", "ghatiya", "bakwas",
    "bekar", "faltu", "nakli", "asli", "sacchi", "jhutha", "gusso", "gussa",
    "nafrat", "pareshan", "dukhi", "naraz", "khatra", "khatro",
}

#: Romanized tokens strong enough that a *single* one means the post carries
#: Hindi or Gujarati. Filipino's shared function words are excluded for the
#: same reason the detector vetoes them above.
ROMAN_INDIC_TRIGGERS = ((HINGLISH_MARKERS | _ROMAN_CONTENT)
                        - _ENGLISH_COLLISIONS - FILIPINO_MARKERS - _AMBIGUOUS)

_INDIC_SCRIPT_RE = re.compile(r"[ऀ-ॿ઀-૿]")
#: URLs and @mentions, dropped before the one-token rule runs — "instagram.com/
#: karo_surat" is a link, not a Hindi verb.
_STRIPPED_RE = re.compile(r"https?://\S+|www\.\S+|@[\w_]+")


def has_indic_content(text: str) -> bool:
    """True when the post carries Hindi or Gujarati anywhere in it.

    Deliberately far looser than `detect_language`: this answers "would an
    English-only reader miss something here?", not "what language is this?".
    One Devanagari or Gujarati character, or one unambiguous romanized marker
    inside otherwise-English prose, is enough — a post reading "the road is
    kharab, bahut problem" is labeled English by every threshold in the
    detector and is still not a post an officer can read.

    Hashtags are NOT stripped here (unlike the language call): a Gujarati-script
    tag is content the analyst cannot read either.
    """
    if not text:
        return False
    if _INDIC_SCRIPT_RE.search(text):
        return True
    # Tokens are expanded through SLANG_MAP by hand rather than by running
    # `normalize`, so the one-token rule can refuse the one- and two-letter
    # entries in it: normalize rewrites a bare "q" to "kyun" and "h" to "hai",
    # which would make "Q: what time does the office open?" a Hindi post.
    for token in latin_tokens(_STRIPPED_RE.sub(" ", text)):
        token = _squeeze(token)
        if len(token) >= 3:
            token = SLANG_MAP.get(token, token)
        if token in ROMAN_INDIC_TRIGGERS:
            return True
    return False
