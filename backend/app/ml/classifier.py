# -*- coding: utf-8 -*-
"""Lexicon signal extraction — the evidence layer under the sentiment models.

This used to emit a four-class threat label ("Incitement to Violence",
"Inflammatory", "Fake News", "Neutral"). It no longer does, and the reason is
worth stating plainly: whether a post will incite violence, or whether a claim
in it is false, are investigative conclusions about the world. A model reading
one post's words cannot establish either, and a console that prints them as
model output invites an analyst to treat a guess as a finding.

What lexicon matching CAN establish is what the post actually contains: violent
vocabulary, hostile framing, abusive terms, mobilization language, and how
strong the strongest matched term is. Those are facts about the text. They feed
three things and claim nothing beyond themselves:

  • the lexicon sentiment model (ml/sentiment.py) — hostile/abusive language is
    intrinsically negative even when no valence word is present
  • the toxicity score and hate flags (ml/toxicity.py)
  • `term_severity` in the concern score (ml/score.py)

`matched_terms` is surfaced to the analyst verbatim as evidence, so every
signal here is auditable against the post text.
"""
from app.ml import lexicons as lx
from app.ml.matcher import match_terms, score
from app.ml.normalize import normalize


def extract_signals(text: str) -> dict:
    """Lexicon evidence for one post. No label, no verdict — just what is there."""
    norm = normalize(text)

    violence = match_terms(norm, lx.VIOLENCE)
    hostility = match_terms(norm, lx.HOSTILITY)
    fake = match_terms(norm, lx.FAKE_MARKERS)
    cta = match_terms(norm, lx.CALL_TO_ACTION)
    officials = match_terms(norm, lx.OFFICIALS)
    abuse = match_terms(norm, lx.ABUSE)

    s_violence = score(violence)
    s_hostility = score(hostility)
    s_fake = score(fake)
    s_cta = score(cta)
    s_abuse = score(abuse)

    matched = violence + hostility + fake + cta + abuse
    matched_terms = [t for t, _ in sorted(matched, key=lambda h: -h[1])][:8]
    term_severity = max((w for _, w in matched), default=0.0)

    # Intent describes the speech act, which the text does support: a post that
    # asks people to gather is a call to action regardless of whether anyone
    # gathers. Kept because the analyst filters on it; no threat claim implied.
    if cta:
        intent = "call_to_action"
    elif fake:
        intent = "rumor"
    elif hostility or abuse:
        intent = "opinion"
    else:
        intent = "informational"

    return {
        "intent": intent,
        "matched_terms": matched_terms,
        "term_severity": term_severity,
        "signals": {
            "violence": round(s_violence, 3),
            "hostility": round(s_hostility, 3),
            "fake_markers": round(s_fake, 3),
            "call_to_action": round(s_cta, 3),
            "targets_official": bool(violence and officials),
            "mobilization": bool(cta and (violence or hostility)),
            "abuse": round(s_abuse, 3),
        },
    }
