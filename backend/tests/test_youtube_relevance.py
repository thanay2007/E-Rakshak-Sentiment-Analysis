# -*- coding: utf-8 -*-
"""Why a Chinese short-drama video was stored as a post from Surat.

YouTube has no geo filter worth using, so the adapter pushes the city into the
query text and then stamps that city onto whatever comes back. When the query
is a bare Devanagari phrase, YouTube's ranking drifts — and drama channels that
stuff twenty languages of tags into every description are what it drifts to. On
the live corpus that produced 51 Chinese and Korean videos filed under Surat,
inflating that district's volume on the heatmap and being sentiment-scored as
if a resident had written them.

The fix is a relevance test, and the distinction it draws is the important
part:

  * a result whose words tie it to neither the query nor any city we watch is
    dropped — it was never a post from here;
  * a result that IS kept takes its location from its own text, not from the
    query. Searching "बच्चा चोर Ahmedabad" returns child-lifting news from
    Moradabad and Begusarai, and stamping those Ahmedabad is what put other
    states' incidents on Gujarat's heatmap;
  * a result is NEVER dropped for the language or script it is written in. That
    is this console's standing rule (a post in Gujarati, Urdu or romanized
    Hinglish has to reach an officer exactly like an English one), and a
    language filter at collection time is an evasion route: anyone who wanted
    to avoid monitoring would simply switch script.

These tests pin both halves.
"""
import pytest

from app.crawlers.youtube import _is_relevant, _mentions, _norm
from app.ml.geo import dominant_city, infer_city
from app.ml.language import detect_language

# The actual title of one of the 51, trimmed.
CHINESE_DRAMA = ("🔥良浩&顧子衿❤️重生後，我親眼目睹丈夫將小三帶回家中偷情，"
                 "並留下監控證據 # 短劇 未成年人禁止")


def _blob(*parts: str) -> str:
    return _norm(" ".join(parts))


def test_the_off_topic_drama_video_is_dropped():
    assert not _is_relevant("रास्ता रोको", _blob(CHINESE_DRAMA))


def test_a_video_that_names_the_city_is_kept_whatever_the_script():
    """The rule that must not be broken while fixing the one above."""
    for text in ("सूरतमां पानी",              # Hindi
                 "સુરતમાં પાણી ભરાયું",   # Gujarati
                 "Surat me paani bharaya, log pareshan"):        # Gujlish
        assert _is_relevant("protest", _blob(text))


def test_a_video_matching_the_search_term_is_kept():
    assert _is_relevant("rasta roko", _blob("RASTA ROKO protest continues", "News"))


def test_an_unrelated_indian_video_is_dropped_too():
    """Measured, not assumed: over four live queries the channel country was
    IN for the recipe videos and the cartoons as much as for the news, so it
    was tried as a third signal and removed. Relevance has to come from the
    words."""
    assert not _is_relevant("bhega thao", _blob("Kothimbir Vadi Recipe #viral #shorts"))
    assert not _is_relevant("bhega thao", _blob("20 Inch Kulcha eating challenge"))


@pytest.mark.parametrize("term,text,expected", [
    ("surat", "Heavy rain in Surat today", True),
    ("rasta roko", "Rasta blocked, roko protest at the crossing", True),
    ("rasta roko", "Rasta blocked by traffic", False),      # only half the term
    ("ho jao", "Something else entirely", False),           # short words ignored
    ("", "anything", False),
])
def test_term_matching(term, text, expected):
    assert _mentions(term, _norm(text)) is expected


def test_the_city_a_bulletin_is_about_beats_the_cities_it_merely_lists():
    """A news description names every city the channel covers.

    `infer_city` answers with whichever comes first in the alias table, so a
    bulletin headlined "Rajkot Bad Roads" was filed under Surat because the
    description mentioned Surat further down. That is a wrong pin on a district
    heatmap an officer allocates by.
    """
    bulletin = ("Rajkot Bad Roads: BJP chief warns of protest. "
                "Also covering Ahmedabad and Surat. Rajkot civic body responds. #rajkot")
    assert infer_city(bulletin)[0] == "Surat"          # the old answer
    assert dominant_city(bulletin)[0] == "Rajkot"      # the right one


def test_a_text_naming_no_watched_city_stays_unlocated():
    """Better an empty location than a confident wrong one."""
    assert dominant_city("Weather update for Delhi and Mumbai") is None


def test_a_chinese_post_is_labelled_as_such_not_as_english():
    """The second half of the same bug: those 51 posts were filed as English.

    Nothing is dropped for it — the label is what sends the post for an English
    gloss, and what lets an analyst filter the noise out of the language panel.
    """
    language, _ = detect_language(CHINESE_DRAMA)
    assert language == "Other"


def test_indic_and_romanized_labels_are_untouched_by_the_foreign_check():
    assert detect_language("સુરતમાં પાણી ભરાયું")[0] == "Gujarati"
    assert detect_language("रास्ता रोको आंदोलन")[0] == "Hindi"
    assert detect_language("naka par police nathi")[0] == "Gujlish"
    assert detect_language("Water supply cut in Adajan since morning")[0] == "English"


def test_one_foreign_word_in_an_english_sentence_is_still_english():
    assert detect_language("Great work by the team 加油 keep it up")[0] == "English"
