# -*- coding: utf-8 -*-
"""Context extraction — what the three sentiment models see besides the words.

The complaint this module answers: the models were scoring bags of words. "આ
રસ્તો ખરાબ છે" and "કોણ કહે છે આ રસ્તો ખરાબ છે? બિલકુલ સરસ છે" share almost
every token and have opposite sentiment; a verified municipal account posting
"water supply disrupted in Katargam" is informational, while the same sentence
from a burner account amplified 40× is a grievance riding a coordinated push.
Neither distinction lives in the tokens.

Context is split in two, and the split is the important part:

**Textual context** (`TextContext`) is derived from the post text ALONE. That
is what makes it usable at training time as well — the training corpora are
plain (text, label) rows with no author or platform, so any feature that needed
metadata could never be learned. `model_input()` renders these cues into a
short deterministic tag prefix which is prepended identically in
train_sentiment.py, train_baseline.py and at inference. Both models therefore
learn what "[q]" (interrogative) or "[rep]" (reported speech) implies instead
of being handed a flag they have never seen.

**Metadata context** (`MetaContext`) is author / platform / reach / geo, known
only at inference. It never touches the model input — it is applied afterwards,
by `apply_context()`, as a bounded calibration of the ensemble's confidence,
and every adjustment it makes is returned as a human-readable reason so the
drawer can show WHY the score moved. Nothing here silently rewrites a label.

Consumed by: ml/sentiment.py, ml/linear_model.py, ml/transformer_engine.py,
ml/ensemble.py, ml/pipeline.py, ml/train_sentiment.py, ml/train_baseline.py.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.ml.normalize import normalize

# ── discourse cue lexicons (multilingual, romanized + native script) ─────────

# Reported / quoted speech: the post relays someone ELSE's words. The valence
# belongs to the person quoted, not to the author, so a confident negative on
# reported speech should not be read as the author's own hostility.
_REPORTED = {
    "said", "says", "claimed", "claims", "alleged", "alleges", "reported",
    "according", "quoted", "statement", "sources",
    "kaha", "bola", "bole", "kehte", "batia", "mutabik", "anusar",
    "kahyu", "kahe", "boliya", "pramane",
    "कहा", "बोले", "कहते", "मुताबिक", "अनुसार", "बयान",
    "કહ્યું", "કહે", "બોલ્યા", "પ્રમાણે", "મુજબ", "નિવેદન",
}

# Conditional / hypothetical: "if they do this, there will be trouble" asserts
# far less than "there will be trouble".
_CONDITIONAL = {
    "if", "unless", "suppose", "would", "could", "might", "maybe", "perhaps",
    "agar", "yadi", "shayad", "to phir", "warna",
    "jo", "kadach", "nahitar",
    "अगर", "यदि", "शायद", "वरना",
    "જો", "કદાચ", "નહીંતર",
}

# Sarcasm / irony cues. Praise words next to these flip: "wah kya service hai"
# is not a compliment.
_SARCASM = {
    "wah", "waah", "kya baat", "bahut khoob", "shabash", "badhai ho",
    "great job", "well done", "thanks a lot", "brilliant", "wonderful",
    "vah", "saras hoon", "majaa aavi gayo",
    "वाह", "क्या बात", "शाबाश", "बधाई हो",
    "વાહ", "શું વાત", "શાબાશ",
}

# The post asks rather than asserts.
_QUESTION_WORDS = {
    "why", "what", "when", "who", "how", "where", "kyun", "kya", "kab", "kaun",
    "kaise", "kahan", "shu", "kem", "kyare", "kon",
    "क्यों", "क्या", "कब", "कौन", "कैसे", "कहाँ",
    "શું", "કેમ", "ક્યારે", "કોણ", "કેવી",
}

# First-person experience ("I waited three hours") vs third-person report.
_FIRST_PERSON = {
    "i", "my", "me", "we", "our", "us", "mine", "hum", "hamara", "mera", "meri",
    "maru", "amaru", "ame", "मैं", "मेरा", "हम", "हमारा", "હું", "મારું", "અમે",
}

# Demands / requests aimed at an institution. Present tense of civic grievance:
# these posts are negative but constructive, not hostile.
_CIVIC_APPEAL = {
    "please", "kindly", "request", "requesting", "solve", "fix", "repair",
    "complaint", "grievance", "action", "resolve", "attention",
    "krupa", "vinanti", "samasya", "fariyad", "nivaran",
    "kripya", "shikayat", "samadhan", "dhyan",
    "कृपया", "शिकायत", "समाधान", "निवारण", "ध्यान",
    "કૃપા", "ફરિયાદ", "સમસ્યા", "નિવારણ", "ધ્યાન",
}

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@[\w_]+")
_HASHTAG_RE = re.compile(r"#(\w+)")
_QUOTE_RE = re.compile(r"[\"“”'‘’«»]{1}.{4,}?[\"“”'‘’«»]{1}", re.DOTALL)
_CAPS_RE = re.compile(r"\b[A-Z]{3,}\b")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)


@dataclass
class TextContext:
    """Discourse structure of the post, derived from the text alone."""

    is_question: bool = False
    is_reported: bool = False
    is_conditional: bool = False
    is_first_person: bool = False
    is_civic_appeal: bool = False
    has_sarcasm_cue: bool = False
    has_contrast: bool = False
    has_quote: bool = False
    caps_ratio: float = 0.0
    exclaim_run: int = 0
    n_hashtags: int = 0
    n_mentions: int = 0
    n_urls: int = 0
    n_emoji: int = 0
    length_band: str = "short"          # short | medium | long
    hashtags: list[str] = field(default_factory=list)

    def tags(self) -> list[str]:
        """The compact tag set rendered into the model input. Order is fixed so
        the string is deterministic — the models tokenize this, so a reordering
        between training and inference would be a silent distribution shift."""
        t: list[str] = []
        if self.is_question:
            t.append("q")
        if self.is_reported:
            t.append("rep")
        if self.is_conditional:
            t.append("cond")
        if self.is_first_person:
            t.append("self")
        if self.is_civic_appeal:
            t.append("appeal")
        if self.has_sarcasm_cue:
            t.append("irony")
        if self.has_contrast:
            t.append("contrast")
        if self.has_quote:
            t.append("quote")
        if self.caps_ratio > 0.25:
            t.append("shout")
        if self.exclaim_run >= 2:
            t.append("emph")
        if self.n_emoji:
            t.append("emoji")
        if self.n_urls:
            t.append("link")
        t.append(self.length_band)
        return t


# Contrastive conjunctions — the clause AFTER them carries the real position.
_CONTRAST = {"but", "however", "though", "although", "lekin", "magar", "par",
             "kintu", "parantu", "pan", "पर", "लेकिन", "मगर", "किंतु",
             "પણ", "પરંતુ", "છતાં"}


def _has_any(tokens: set[str], text: str, vocab: set[str]) -> bool:
    """True when a vocab entry appears as a token, or as a substring for the
    multi-word / Indic entries that tokenization would split."""
    if tokens & vocab:
        return True
    return any(" " in v or not v.isascii() for v in vocab if v in text)


def build_text_context(text: str) -> TextContext:
    """Discourse features of one post. Pure function of the text — safe to call
    on training rows, which is the whole point."""
    norm = normalize(text)
    tokens = set(re.findall(r"\w+", norm.lower()))

    letters = sum(1 for c in text if c.isalpha())
    caps = sum(1 for c in text if c.isupper())
    n_words = len(text.split())

    ctx = TextContext(
        is_question="?" in text or bool(tokens & _QUESTION_WORDS),
        is_reported=_has_any(tokens, norm, _REPORTED),
        is_conditional=_has_any(tokens, norm, _CONDITIONAL),
        is_first_person=bool(tokens & _FIRST_PERSON),
        is_civic_appeal=_has_any(tokens, norm, _CIVIC_APPEAL),
        has_sarcasm_cue=_has_any(tokens, norm, _SARCASM),
        has_contrast=bool(tokens & _CONTRAST),
        has_quote=bool(_QUOTE_RE.search(text)),
        caps_ratio=(caps / letters) if letters else 0.0,
        exclaim_run=text.count("!"),
        n_hashtags=len(_HASHTAG_RE.findall(text)),
        n_mentions=len(_MENTION_RE.findall(text)),
        n_urls=len(_URL_RE.findall(text)),
        n_emoji=len(_EMOJI_RE.findall(text)),
        length_band="short" if n_words <= 12 else "medium" if n_words <= 40 else "long",
        hashtags=[h.lower() for h in _HASHTAG_RE.findall(text)],
    )
    return ctx


def main_clause(text: str) -> str:
    """The clause the author actually asserts.

    After a contrastive conjunction the second clause carries the position
    ("service slow hai but staff bahut helpful"), so that is what the models
    should weigh most. Returns the whole text when there is no contrast.
    """
    lowered = text.lower()
    best = -1
    for c in _CONTRAST:
        idx = lowered.rfind(f" {c} ")
        if idx > best:
            best = idx
    if best <= 0 or best > len(text) - 6:
        return text
    return text[best:].strip()


# ── the shared model input ──────────────────────────────────────────────────
# Both the transformer and the classical model are fed EXACTLY this string, at
# training time and at inference time. The tag prefix is cheap (a handful of
# tokens) and gives a model that only sees text a way to condition on structure.

CONTEXT_PREFIX_VERSION = "ctx1"


def model_input(text: str, tctx: TextContext | None = None) -> str:
    """Render text + its discourse tags into the string the models consume.

    Example:
        "[ctx1 q self short] why is there no water in Katargam since morning"
    """
    tctx = tctx or build_text_context(text)
    tags = " ".join(tctx.tags())
    return f"[{CONTEXT_PREFIX_VERSION} {tags}] {text.strip()}"


def model_inputs(texts: list[str]) -> tuple[list[str], list[TextContext]]:
    """Batch helper — the contexts are returned because the callers need them
    again for the lexicon model and the calibration step."""
    ctxs = [build_text_context(t) for t in texts]
    return [model_input(t, c) for t, c in zip(texts, ctxs)], ctxs


# ── metadata context (inference only) ───────────────────────────────────────

@dataclass
class MetaContext:
    """Everything known about the post that is not its text."""

    platform: str = ""
    author_handle: str = ""
    author_verified: bool = False
    author_followers: int = 0
    author_account_age_days: int = 0
    is_amplified: bool = False
    engagement: dict = field(default_factory=dict)
    location: str = ""
    language: str = "English"
    code_mixed: bool = False

    @property
    def reach(self) -> float:
        """Log-scaled audience size in [0,1]. 100 followers ≈ 0.29, 100k ≈ 0.83."""
        return min(1.0, math.log10(1 + max(0, self.author_followers)) / 6)

    @property
    def virality(self) -> float:
        """Log-scaled interaction volume in [0,1], +0.15 inside an amplified burst."""
        e = self.engagement or {}
        raw = (e.get("likes", 0) + 3 * e.get("shares", 0)
               + 2 * e.get("comments", 0) + e.get("views", 0) / 50)
        v = min(1.0, math.log10(1 + max(0, raw)) / 4)
        return min(1.0, v + 0.15) if self.is_amplified else v

    @property
    def is_institutional(self) -> bool:
        """A verified account with real reach and a real history — a municipal
        corporation, a police handle, a news desk. Their negative posts are
        usually reporting a problem, not expressing hostility about it."""
        return (self.author_verified and self.author_followers >= 10_000
                and self.author_account_age_days >= 365)

    @property
    def is_throwaway(self) -> bool:
        """New account, no audience. Not evidence of anything on its own, but it
        is why a confident reading of a burner's post deserves less weight."""
        return (not self.author_verified and self.author_followers < 100
                and 0 < self.author_account_age_days < 30)


def meta_from_raw(raw, language: str = "English", code_mixed: bool = False) -> MetaContext:
    """Build a MetaContext from a RawPost (ingestion) or a Post row (re-scoring)."""
    return MetaContext(
        platform=getattr(raw, "platform", "") or "",
        author_handle=getattr(raw, "author_handle", "") or "",
        author_verified=bool(getattr(raw, "author_verified", False)),
        author_followers=int(getattr(raw, "author_followers", 0) or 0),
        author_account_age_days=int(getattr(raw, "author_account_age_days", 0) or 0),
        is_amplified=bool(getattr(raw, "is_amplified", False)),
        engagement=getattr(raw, "engagement", {}) or {},
        location=getattr(raw, "location", "") or "",
        language=language,
        code_mixed=code_mixed,
    )


# ── calibration ─────────────────────────────────────────────────────────────

def context_adjustments(tctx: TextContext, mctx: MetaContext) -> list[dict]:
    """Bounded confidence adjustments justified by context, each with a reason.

    Returns [{"factor", "delta", "reason"}]. `delta` is added to the ensemble's
    confidence and clamped by the caller; nothing here can change a LABEL — a
    context signal is a reason to be more or less sure, never a reason to
    decide the opposite of what the text says.
    """
    adj: list[dict] = []

    if tctx.is_reported:
        adj.append({"factor": "reported speech", "delta": -0.08,
                    "reason": "The post relays someone else's words, so the "
                              "valence may belong to the person quoted rather "
                              "than the author."})
    if tctx.is_conditional:
        adj.append({"factor": "conditional framing", "delta": -0.06,
                    "reason": "Hypothetical or conditional phrasing asserts less "
                              "than a direct statement."})
    if tctx.is_question and not tctx.is_first_person:
        adj.append({"factor": "interrogative", "delta": -0.05,
                    "reason": "The post asks rather than asserts; rhetorical "
                              "questions carry weaker polarity than claims."})
    if tctx.has_sarcasm_cue:
        adj.append({"factor": "irony cue", "delta": -0.10,
                    "reason": "Praise words appear next to an irony marker, so "
                              "surface polarity is unreliable here."})
    if tctx.is_first_person and not tctx.is_reported:
        adj.append({"factor": "first-hand account", "delta": +0.05,
                    "reason": "First-person experience — the author is stating "
                              "their own position directly."})
    if tctx.has_contrast:
        adj.append({"factor": "contrastive clause", "delta": -0.04,
                    "reason": "A contrastive conjunction splits the post; the "
                              "final clause was weighted as the author's position."})
    if tctx.caps_ratio > 0.25 or tctx.exclaim_run >= 3:
        adj.append({"factor": "emphasis", "delta": +0.04,
                    "reason": "Sustained capitals or repeated exclamation marks "
                              "intensify whichever polarity is present."})

    if mctx.is_institutional:
        adj.append({"factor": "institutional account", "delta": -0.06,
                    "reason": f"@{mctx.author_handle} is a verified account with "
                              f"{mctx.author_followers:,} followers — negative "
                              "wording here usually reports a problem rather "
                              "than expressing it."})
    if mctx.is_throwaway:
        adj.append({"factor": "low-history account", "delta": -0.05,
                    "reason": f"@{mctx.author_handle} is {mctx.author_account_age_days} "
                              "days old with a negligible audience; treat a "
                              "confident reading of it cautiously."})
    if mctx.is_amplified:
        adj.append({"factor": "coordinated amplification", "delta": +0.05,
                    "reason": "The post is part of a detected amplification "
                              "burst, so its reach is engineered rather than organic."})
    if tctx.is_civic_appeal:
        adj.append({"factor": "civic appeal", "delta": -0.03,
                    "reason": "The post asks an authority to fix something — "
                              "negative in tone but constructive in intent."})
    return adj
