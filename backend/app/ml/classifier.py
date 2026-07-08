"""Lite threat classifier — lexicon + heuristic layer.

Produces the exact 4 labels the UI uses: "Incitement to Violence",
"Inflammatory", "Fake News", "Neutral" — plus per-class probabilities,
matched evidence terms and an intent label. Zero model downloads, <1ms/post,
and fully multilingual via the lexicons. Swapped out transparently for the
fine-tuned / zero-shot transformer when NLP_MODE=full.
"""
from app.ml import lexicons as lx
from app.ml.matcher import match_terms, score
from app.ml.normalize import normalize

LABELS = ["Incitement to Violence", "Inflammatory", "Fake News", "Neutral"]


def classify(text: str) -> dict:
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
    s_official = score(officials)
    s_abuse = score(abuse)

    # ── Category raw scores ──────────────────────────────────────────────
    # Incitement: violent language, amplified by mobilization and by
    # violence directed at office-holders.
    incitement = s_violence
    if violence and cta:
        incitement += 0.8 * s_cta          # "gather at X and teach them a lesson"
    if violence and officials:
        incitement += 0.7 * s_official     # threat against an office-holder
    if violence and hostility:
        incitement += 0.5 * s_hostility    # hostile framing + violence = incitement, not mere hostility
    if cta and hostility and not violence:
        # mobilizing people against a group IS incitement even without an
        # explicit violence word ("everyone gather at X, enough of them")
        incitement += 1.0 * s_cta + 0.4 * s_hostility

    # Inflammatory: hostility/exclusion + abuse, minus what incitement claimed
    inflammatory = s_hostility + 0.5 * s_abuse

    # Fake news: misinformation framing; forward/share pressure is a strong tell
    fake_news = s_fake

    # Neutral floor: constant baseline that wins when nothing fires
    neutral = 0.55

    raw = {
        "Incitement to Violence": incitement,
        "Inflammatory": inflammatory,
        "Fake News": fake_news,
        "Neutral": neutral,
    }
    total = sum(raw.values()) or 1.0
    probs = {k: round(v / total, 4) for k, v in raw.items()}
    label = max(probs, key=probs.get)
    confidence = probs[label]

    # ── Intent layer ─────────────────────────────────────────────────────
    if label == "Incitement to Violence":
        intent = "threat"
    elif cta:
        intent = "call_to_action"
    elif label == "Fake News":
        intent = "rumor"
    elif label == "Inflammatory":
        intent = "opinion"
    else:
        intent = "informational"

    matched = violence + hostility + fake + cta + abuse
    matched_terms = [t for t, _ in sorted(matched, key=lambda h: -h[1])][:8]
    keyword_severity = max((w for _, w in matched), default=0.0)

    return {
        "label": label,
        "confidence": confidence,
        "probs": probs,
        "intent": intent,
        "matched_terms": matched_terms,
        "keyword_severity": keyword_severity,
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
