# -*- coding: utf-8 -*-
"""What earns a post an English gloss.

The rule that matters here is deliberately looser than language detection: a
post can be *labeled* English — correctly — and still contain the one Gujarati
clause that carries the grievance. Those were the posts reaching officers with
no translation at all, because the old gate was `language != "English"` plus a
script check, and neither fires on romanized text inside English prose.

The other half of these cases is the half that keeps the gate honest. Every
translation costs an LLM call out of a shared daily budget, so a rule that
answers "yes" to ordinary English city-desk posts is not a safe default — it is
a rule that drains the budget before the posts that need it are reached.
"""
import pytest

from app.ml.language import detect_language, has_indic_content
from app.services.groq_verifier import needs_translation


def _gate(text: str) -> bool:
    """The production path: detect, then decide, exactly as ingest does."""
    language, _ = detect_language(text)
    return needs_translation(text, {"language": language})


NEEDS_GLOSS = [
    # One romanized word inside otherwise-English prose — the reported gap.
    "The road is kharab, bahut problem here every monsoon",
    "Ward office ne complaint kari but nothing happened",
    # One word of Indic script, ditto.
    "Traffic jam near ring road આજે સવારે",
    "Heavy rain expected tomorrow #સુરત",
    # Wholly non-English, which the old gate already caught.
    "naka par police nathi",
    "Rasta par pani bharai gayu che",
]

ALREADY_READABLE = [
    "Water supply cut in Adajan since morning",
    "Great work by Surat police team, very professional response",
    "Police arrested two men near the market this evening",
    "Commissioner inaugurated the new traffic signal at Ring Road",
    # Marker words that are also ordinary English words. "log", "mat", "pan",
    # "mate", "male" all sit in the romanized lists; one of them is a coincidence.
    "The society vote was held today and the male officer logged it",
    # Filipino shares function words with the Hindi lists and is vetoed
    # upstream; it must not sneak back in through the looser gate.
    "Sana ma-approve na ang permit natin dito sa barangay",
]


@pytest.mark.parametrize("text", NEEDS_GLOSS)
def test_indic_content_anywhere_earns_a_translation(text):
    assert _gate(text) is True


@pytest.mark.parametrize("text", ALREADY_READABLE)
def test_plain_english_is_not_sent_to_the_translator(text):
    assert _gate(text) is False


def test_normalizer_shorthand_does_not_manufacture_hindi():
    """`normalize` rewrites a bare "q" to "kyun" and "h" to "hai" — useful for
    the lexicon matchers, ruinous as a translation trigger. The one-token rule
    expands only tokens of three characters or more for that reason."""
    assert has_indic_content("Q: what time does the office open?") is False
    assert has_indic_content("Section 144 h notice issued") is False
    # …while genuine three-letter shorthand still expands and still counts.
    assert has_indic_content("bht ganda rasta") is True


def test_a_post_already_glossed_is_never_retranslated():
    assert needs_translation("કંઈક ખરાબ થયું", {"language": "Gujarati",
                                                "translation": "something bad happened"}) is False


def test_stray_indic_marks_the_post_code_mixed():
    """The English label is right; the code_mixed flag is what carries "there is
    something here you cannot read" into the database, so the untranslated
    count and the backfill can both find the post later."""
    language, mixed = detect_language("The drainage is kharab near the school")
    assert language == "English"
    assert mixed is True
