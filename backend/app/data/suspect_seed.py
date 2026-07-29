# -*- coding: utf-8 -*-
"""Demo seed for the suspect registry.

These are synthetic records, not real people — every one is flagged
`source="seed"` and says so in its notes, and none of them ships a face
template, because a biometric template can only honestly come from a photo
somebody actually enrolled. A seeded record is therefore *not* matchable until
an analyst attaches a reference photo, which is exactly the workflow the tool is
meant to teach.

What the seed does contribute is linkage: each record's known handles are bound
to accounts that genuinely exist in the monitored corpus (highest-threat posters
and a bot-net member), so opening a dossier immediately shows real posts, real
threat scores and real coordination clusters rather than an empty shell.
"""
from __future__ import annotations

import logging

from sqlmodel import col, select

from app.database import session_scope
from app.models import Post, Suspect

log = logging.getLogger(__name__)

# (name, aliases, record_type, risk, status, jurisdiction, location, charges, notes)
_TEMPLATES = [
    {
        "full_name": "Ravi Bhai Solanki",
        "aliases": ["Ravi Bhai", "RS"],
        "record_type": "wanted",
        "risk_level": "critical",
        "status": "at_large",
        "jurisdiction": "Athwa Police Station, Surat",
        "last_known_location": "Surat",
        "wanted_since": "2026-05-14",
        "convictions": 1,
        "case_ids": ["FIR 0142/2026 — Athwa PS", "FIR 0311/2025 — Varachha PS"],
        "charges": [
            {"section": "IPC 153A", "description": "Promoting enmity between groups on grounds of religion",
             "status": "charged", "date": "2026-05-14"},
            {"section": "IPC 505(1)(b)", "description": "Statements conducing to public mischief",
             "status": "charged", "date": "2026-05-14"},
            {"section": "IT Act 66F", "description": "Cyber terrorism — coordinated rumor campaign",
             "status": "under trial", "date": "2025-11-02"},
        ],
        "identifying_marks": "Scar on left forearm",
        "gender": "male", "age": 34, "nationality": "Indian",
    },
    {
        "full_name": "Imran Shaikh",
        "aliases": ["Immu"],
        "record_type": "criminal",
        "risk_level": "high",
        "status": "on_bail",
        "jurisdiction": "Cyber Cell, Ahmedabad",
        "last_known_location": "Ahmedabad",
        "convictions": 2,
        "case_ids": ["FIR 0087/2024 — Cyber Cell Ahmedabad"],
        "charges": [
            {"section": "IPC 295A", "description": "Deliberate acts intended to outrage religious feelings",
             "status": "convicted", "date": "2024-03-19"},
            {"section": "IPC 469", "description": "Forgery for the purpose of harming reputation",
             "status": "convicted", "date": "2024-03-19"},
        ],
        "gender": "male", "age": 29, "nationality": "Indian",
    },
    {
        "full_name": "Kiran Patel",
        "aliases": ["Kiran bhai", "K.P."],
        "record_type": "person_of_interest",
        "risk_level": "medium",
        "status": "under_investigation",
        "jurisdiction": "SOG, Rajkot",
        "last_known_location": "Rajkot",
        "case_ids": ["Enquiry 22/2026 — SOG Rajkot"],
        "charges": [],
        "notes_extra": "Named in an ongoing enquiry into a boycott-campaign poster network. "
                       "No charges filed.",
        "gender": "male", "age": 41, "nationality": "Indian",
    },
    {
        "full_name": "Meera Joshi",
        "aliases": [],
        "record_type": "missing",
        "risk_level": "low",
        "status": "under_investigation",
        "jurisdiction": "Vadodara City PS",
        "last_known_location": "Vadodara",
        "case_ids": ["MP 0034/2026 — Vadodara City PS"],
        "charges": [],
        "notes_extra": "Missing-person report. Registry entry exists so any face match in "
                       "circulating media routes straight to the investigating officer.",
        "gender": "female", "age": 22, "nationality": "Indian",
    },
]

_SEED_NOTE = ("SYNTHETIC DEMO RECORD — not a real person. Seeded so the identification "
              "workflow is demonstrable; enrol a reference photo to make it matchable.")


def _corpus_handles(limit: int) -> list[dict]:
    """Pick real accounts from the monitored corpus so seeded dossiers are live.

    Preference order: the highest-threat posters first, then a bot-net member,
    so the seeded records demonstrate both the 'hostile individual' and the
    'coordinated account' shapes of the dossier.
    """
    with session_scope() as s:
        hot = s.exec(
            select(Post).where(Post.threat_label != "Neutral")
            .order_by(col(Post.threat_score).desc()).limit(limit * 3)
        ).all()
        bots = s.exec(
            select(Post).where(col(Post.author_handle).like("desh_sachai%")).limit(3)
        ).all()

    seen, out = set(), []
    for p in list(hot) + list(bots):
        if p.author_handle in seen:
            continue
        seen.add(p.author_handle)
        out.append({"platform": p.platform, "handle": p.author_handle,
                    "url": p.url.rsplit("/", 2)[0] if p.url else "",
                    "note": f"active in monitored corpus ({p.threat_label})"})
        if len(out) >= limit:
            break
    return out


def seed_suspects_if_empty() -> int:
    """Create the demo registry once, on a fresh database."""
    with session_scope() as s:
        if s.exec(select(Suspect).limit(1)).first():
            return 0

    handles = _corpus_handles(len(_TEMPLATES) * 2)
    added = 0
    with session_scope() as s:
        for i, tpl in enumerate(_TEMPLATES):
            data = dict(tpl)
            extra = data.pop("notes_extra", "")
            data["notes"] = (extra + " " if extra else "") + _SEED_NOTE
            # two handles per record where the corpus has enough accounts
            data["social_handles"] = handles[i * 2:i * 2 + 2]
            s.add(Suspect(**data, source="seed"))
            added += 1
        s.commit()
    log.info("seeded %d demo suspect record(s)", added)
    return added
