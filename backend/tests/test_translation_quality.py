"""A "translation" that leaves the romanized Gujarati in place is not one.

The case behind this: a Gujlish post whose quoted speech ("maru banai dejo ne
bija loko nu pachi") came back verbatim inside an otherwise tidied English
sentence, so the drawer showed two near-identical paragraphs. The check below
is what decides a translation must be retried, and what makes a stored one be
redone.

Run:  cd backend && python -m pytest tests/test_translation_quality.py -q
"""
from app.services.groq_verifier import translation_incomplete, untranslated_spans

SRC = ('Hate I truly hate overconfident uncles at Yaadgar omelette, like bro stop '
       'what the fuck is "maru banai dejo ne bija loko nu pachi" and then they '
       'casually says in front of people "apda ne to bau pehle thi odkhe che"')


def test_quoted_gujlish_copied_through_is_incomplete():
    leaked = ('I hate overconfident uncles at Yaadgar Omelette, like bro what the '
              'fuck is "maru banai dejo ne bija loko nu pachi"')
    assert translation_incomplete(SRC, leaked)


def test_full_english_with_rare_words_and_names_is_complete():
    good = ('I truly hate overconfident uncles at Yaadgar Omelette, like bro what '
            'the fuck is "make it for me first and the others later"')
    assert not translation_incomplete(SRC, good)


def test_a_copy_of_the_original_is_not_a_translation():
    assert translation_incomplete(SRC, SRC)
    assert translation_incomplete(SRC, "")


def test_hashtags_and_handles_are_allowed_to_stay():
    assert not translation_incomplete(
        "Surat ma aaje bau traffic che #gujaratsamachar @surat_police",
        "Heavy traffic in Surat today #gujaratsamachar @surat_police")


def test_spans_name_every_leftover_quote():
    spans = untranslated_spans(SRC, SRC)
    assert "maru banai dejo ne bija loko nu pachi" in spans
    assert "apda ne to bau pehle thi odkhe che" in spans
