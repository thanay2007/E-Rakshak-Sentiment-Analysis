"""News corroboration must search for the post's subject and count only
articles about it.

The case that motivated this: a Gujarati post mourning a father, tagged
#nanapatekar #malharpatekar. The query was its first five words ("Losing
father deep trauma son—an"), NewsAPI answered with an anime listing and an
op-ed, and the drawer reported "14 reports — supported by news".

Run:  cd backend && python -m pytest tests/test_fact_check_relevance.py -q
"""
from app.services.fact_check import _entities, _query_for, _relevant

POST = ("Losing a father is a deep trauma for a son—an emptiness that time can "
        "never fully fill. #malharpatekar #nanapatekar #indialivenews2024")


def test_query_uses_the_subject_hashtags_not_the_opening_words():
    assert _query_for({}, POST) == "malharpatekar nanapatekar"


def test_channel_and_year_hashtags_are_not_a_subject():
    assert "indialivenews2024" not in _entities(POST)


def test_camel_case_hashtag_becomes_a_name():
    assert _entities("Sad news #NanaPatekar") == ["Nana Patekar"]


def test_sentence_initial_capital_is_not_a_name():
    assert _entities("Losing a father hurts.") == []


def test_names_inside_a_sentence_are_found():
    assert "Surat Police" in _entities("Stones were thrown and Surat Police responded.")


def test_article_naming_the_subject_is_relevant_even_with_spaces():
    ents = _entities(POST)
    assert _relevant({"title": "Nana Patekar's son Malhar performs last rites"}, "", ents)


def test_unrelated_articles_are_dropped():
    ents = _entities(POST)
    for title in ("Every Isekai Anime Coming To Streaming In October",
                  "How to Cure a Feminist",
                  "'For our son, death is a release': Harish Rana's father thanks SC"):
        assert not _relevant({"title": title}, "", ents), title


def test_plain_word_query_needs_most_words_to_match():
    q = _query_for({}, "Losing a father is a deep trauma for a son.")
    assert not _relevant({"title": "For our son, death is a release: father thanks SC"}, q, [])
    assert _relevant({"title": "Losing a father: the deep trauma sons carry"}, q, [])


def test_stored_junk_evidence_is_cleaned_on_read():
    """Records saved before the relevance filter existed are re-judged when
    read, so the drawer stops showing them as support without a re-fetch."""
    from app.services.fact_check import revalidate

    stored = {
        "checked": True, "query": "Losing father deep trauma son—an",
        "verdict": "corroborated", "sources": ["Google News RSS", "NewsAPI.org"],
        "matches": [{"title": "How to Cure a Feminist", "api": "NewsAPI.org"},
                    {"title": "Every Isekai Anime Coming To Streaming", "api": "NewsAPI.org"}],
    }
    out = revalidate(stored, POST)
    assert out["verdict"] == "uncorroborated"
    assert out["matches"] == [] and out["sources"] == []
    assert out["note"].startswith("No related news found")


def test_revalidate_leaves_good_records_alone():
    from app.services.fact_check import revalidate

    good = {"checked": True, "query": "malharpatekar nanapatekar", "verdict": "corroborated",
            "matches": [{"title": "Nana Patekar's son Malhar performs last rites"}]}
    assert revalidate(good, POST) is good
