# -*- coding: utf-8 -*-
"""Identity dossier — everything the system knows about an identified person.

This is what runs the moment a face in evidence matches a record: the match is
only the key, and this module opens every drawer it unlocks.

  the record        charges, case IDs, custody status, jurisdiction, risk level
  social footprint  each known handle expanded through the existing sleuth
                    dossier (corpus activity, threat profile, bot/authenticity
                    score, coordination clusters) plus live cross-platform
                    username enumeration for accounts we have not seen post
  their posts       every monitored post from those handles, worst-first
  linked alerts     alerts already raised on those posts
  timeline          charges, posts and alerts merged into one chronology

The handle expansions run concurrently — a record with five known accounts
would otherwise serialise five rounds of network probes.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime

from sqlmodel import Session, col, select

from app.models import Alert, FaceSearchLog, Post, Suspect
from app.osint import face_gallery
from app.osint.face_db import match_encoding
from app.osint.face_db import to_dict as suspect_to_dict
from app.osint.sleuth import build_dossier
from app.services.serializers import iso

log = logging.getLogger(__name__)

_MAX_HANDLES_DEEP = 6      # cap the live probing fan-out per record
_MAX_POSTS = 25


def _handles(suspect: Suspect) -> list[dict]:
    out, seen = [], set()
    for h in (suspect.social_handles or []):
        handle = (h.get("handle") or "").strip().lstrip("@")
        if not handle or handle.lower() in seen:
            continue
        seen.add(handle.lower())
        out.append({
            "platform": h.get("platform", ""),
            "handle": handle,
            "url": h.get("url", ""),
            "note": h.get("note", ""),
        })
    return out


def _posts_for(session: Session, handles: list[str]) -> list[Post]:
    if not handles:
        return []
    lowered = [h.lower() for h in handles]
    rows = session.exec(
        select(Post).where(col(Post.author_handle).in_(lowered))
        .order_by(col(Post.created_at).desc())
    ).all()
    if not rows:
        # handles are stored lowercase by the ingestion pipeline, but a record
        # may carry display casing — fall back to a case-insensitive sweep
        rows = [p for p in session.exec(select(Post)).all()
                if p.author_handle.lower() in lowered]
    return list(rows)


def _post_brief(p: Post) -> dict:
    return {
        "id": p.id,
        "platform": p.platform,
        "author_handle": p.author_handle,
        "text": (p.translation or p.text)[:400],
        "original_text": p.text[:400],
        "language": p.language,
        "sentiment_label": p.sentiment_label,
        "concern_score": round(p.concern_score, 1),
        "sentiment_label": p.sentiment_label,
        "location": p.location,
        "engagement": p.engagement or {},
        "media_urls": p.media_urls or [],
        "is_amplified": p.is_amplified,
        "cluster_id": p.cluster_id,
        "url": p.url,
        "created_at": iso(p.created_at),
    }


def _threat_summary(posts: list[Post]) -> dict:
    if not posts:
        return {"posts": 0}
    scores = [p.concern_score for p in posts]
    return {
        "posts": len(posts),
        "avg_concern_score": round(sum(scores) / len(scores), 1),
        "max_concern_score": round(max(scores), 1),
        "label_breakdown": dict(Counter(p.sentiment_label for p in posts)),
        "sentiment_breakdown": dict(Counter(p.sentiment_label for p in posts)),
        "non_neutral_posts": sum(p.sentiment_label == "negative" for p in posts),
        "platforms": sorted({p.platform for p in posts}),
        "locations": sorted({p.location for p in posts if p.location}),
        "amplified_posts": sum(bool(p.is_amplified) for p in posts),
        "clusters": sorted({p.cluster_id for p in posts if p.cluster_id}),
        "first_seen": iso(min(p.created_at for p in posts)),
        "last_seen": iso(max(p.created_at for p in posts)),
    }


def _alerts_for(session: Session, post_ids: list[str]) -> list[dict]:
    if not post_ids:
        return []
    rows = session.exec(
        select(Alert).where(col(Alert.post_id).in_(post_ids))
        .order_by(col(Alert.created_at).desc())
    ).all()
    return [{
        "id": a.id, "post_id": a.post_id, "severity": a.severity,
        "status": a.status, "title": a.title, "summary": a.summary,
        "category": a.category, "location": a.location, "platform": a.platform,
        "concern_score": round(a.concern_score, 1), "created_at": iso(a.created_at),
    } for a in rows]


def _timeline(suspect: Suspect, posts: list[Post], alerts: list[dict]) -> list[dict]:
    """Charges, posts and alerts merged into one reverse-chronological view.

    Charge dates are free-text on the record, so anything unparseable is kept
    with a null sort key and lands at the end rather than being dropped.
    """
    events: list[dict] = []
    for c in (suspect.charges or []):
        events.append({
            "kind": "charge",
            "at": c.get("date", ""),
            "title": c.get("section") or "Charge",
            "detail": c.get("description", ""),
            "status": c.get("status", ""),
        })
    for p in posts[:_MAX_POSTS]:
        events.append({
            "kind": "post",
            "at": iso(p.created_at),
            "title": f"{p.platform} post — {p.sentiment_label}",
            "detail": (p.translation or p.text)[:180],
            "status": f"threat {round(p.concern_score)}",
            "ref": p.id,
        })
    for a in alerts:
        events.append({
            "kind": "alert",
            "at": a["created_at"],
            "title": a["title"],
            "detail": a["summary"][:180],
            "status": a["severity"],
            "ref": a["id"],
        })

    def key(e):
        try:
            return datetime.fromisoformat(e["at"].rstrip("Z"))
        except Exception:
            return datetime.min

    return sorted(events, key=key, reverse=True)


async def _expand_handle(h: dict, deep: bool) -> dict:
    """Run the full sleuth dossier for one known handle."""
    try:
        dossier = await build_dossier(h["handle"], do_username_lookup=deep)
    except Exception as exc:
        log.warning("dossier for %s failed: %s", h["handle"], exc)
        return {**h, "error": str(exc)}
    return {
        **h,
        "in_corpus": bool(dossier.get("found")),
        "profile": dossier.get("profile", {}),
        "activity": dossier.get("activity", {}),
        "threat_profile": dossier.get("threat_profile", {}),
        "authenticity": dossier.get("authenticity", {}),
        "coordination": dossier.get("coordination", {}),
        "notable_posts": dossier.get("notable_posts", []),
        "cross_platform": dossier.get("cross_platform", {}),
    }


def _summary(suspect: Suspect, posts: list[Post], alerts: list[dict],
             accounts: list[dict]) -> str:
    bits = [f"{suspect.full_name} is on record as "
            f"{suspect.record_type.replace('_', ' ')} "
            f"({suspect.risk_level} risk, status: {suspect.status.replace('_', ' ')})"]
    if suspect.charges:
        bits.append(f"{len(suspect.charges)} charge(s) across "
                    f"{len(suspect.case_ids or []) or 1} case file(s)")
    if suspect.last_known_location:
        bits.append(f"last known at {suspect.last_known_location}")
    if accounts:
        live = sum(1 for a in accounts if a.get("in_corpus"))
        bits.append(f"{len(accounts)} known account(s), {live} of them active in the "
                    f"monitored corpus")
    if posts:
        hostile = sum(p.sentiment_label == "negative" for p in posts)
        bits.append(f"{len(posts)} monitored post(s), {hostile} non-neutral")
    if alerts:
        bits.append(f"{len(alerts)} alert(s) already raised")
    return "; ".join(bits) + "."


async def build_identity_dossier(session: Session, suspect: Suspect, *,
                                 deep: bool = True) -> dict:
    """Assemble the full picture for an identified person.

    `deep=False` skips live cross-platform username enumeration (18 HTTP probes
    per handle) — used when several faces in one photo all match records and the
    request would otherwise stall.
    """
    handles = _handles(suspect)
    posts = _posts_for(session, [h["handle"] for h in handles])
    posts.sort(key=lambda p: (p.concern_score, p.created_at), reverse=True)
    alerts = _alerts_for(session, [p.id for p in posts])

    accounts: list[dict] = []
    if handles:
        expansions = await asyncio.gather(
            *[_expand_handle(h, deep) for h in handles[:_MAX_HANDLES_DEEP]],
            return_exceptions=True,
        )
        for h, res in zip(handles[:_MAX_HANDLES_DEEP], expansions):
            accounts.append(res if isinstance(res, dict) else {**h, "error": str(res)})
        # anything past the fan-out cap is listed without expansion
        accounts += [{**h, "not_expanded": True} for h in handles[_MAX_HANDLES_DEEP:]]

    return {
        "suspect": suspect_to_dict(suspect),
        "summary": _summary(suspect, posts, alerts, accounts),
        "social_footprint": {
            "handles_known": len(handles),
            "handles_expanded": min(len(handles), _MAX_HANDLES_DEEP),
            "deep_lookup": deep,
            "accounts": accounts,
        },
        "monitored_posts": {
            "total": len(posts),
            "returned": min(len(posts), _MAX_POSTS),
            "items": [_post_brief(p) for p in posts[:_MAX_POSTS]],
        },
        "threat_summary": _threat_summary(posts),
        "linked_alerts": alerts,
        "timeline": _timeline(suspect, posts, alerts),
    }


async def identify_faces(session: Session, analysis: dict, *,
                         deep: bool = True, filename: str = "") -> dict:
    """Match every detected face against the registry and the reference gallery.

    Two searches, kept apart on purpose. The registry answers "is this person on
    our records" and a hit there opens a dossier; the gallery (`face_gallery`,
    the `pics/` folder) answers "do we know who this is at all" and a hit there
    is only a name. Folding the second into the first would mean a footballer in
    a viral photo arriving on screen dressed as a criminal record.

    Mutates `analysis["forensics"]["face_matches"]` in place: each face gains an
    `identity` block (with a `known_person` sub-block for the gallery result)
    and its raw 128-d `encoding` is REMOVED. That strip is the point — the
    embedding is biometric data and has no business travelling to a browser; it
    exists only long enough to run the comparison server-side.
    """
    forensics = (analysis or {}).get("forensics") or {}
    faces = forensics.get("face_matches") or []
    if not faces:
        return {
            "faces_detected": 0,
            "identified": 0,
            "candidates": 0,
            "known_people": 0,
            "identities": {},
            "registry": _registry_stats(session),
            "gallery": _gallery_stats(session),
            "summary": (forensics.get("reason") or forensics.get("note")
                        or "No faces detected in this media."),
        }

    identified_ids: list[str] = []
    candidate_count = 0
    known_names: list[str] = []
    log_rows: list[dict] = []

    for face in faces:
        encoding = face.pop("encoding", None)
        if not encoding:
            face["identity"] = {
                "identified": False,
                "searched": False,
                "reason": "Face quality too low to search: "
                          + "; ".join(face.get("quality", {}).get("issues", [])
                                      or ["no embedding"]),
                "candidates": [],
            }
            continue

        result = match_encoding(session, encoding)
        result["searched"] = True

        # The reference gallery, searched for every face regardless of what the
        # registry found: a record hit and a known name are complementary, and
        # an analyst wants both ("this is Ronaldo" AND "he is not on record").
        try:
            known = face_gallery.match(session, encoding)
        except Exception as exc:
            log.warning("reference gallery search failed: %s", exc)
            known = {"identified": False, "searched": False, "reason": str(exc),
                     "candidates": []}
        result["known_person"] = known
        if known.get("identified") and known.get("match"):
            face["known_person"] = known["match"]["name"]
            if known["match"]["name"] not in known_names:
                known_names.append(known["match"]["name"])

        face["identity"] = result

        top = result.get("match")
        if result.get("identified") and top:
            face["matched_suspect"] = top["full_name"]
            face["confidence"] = top["confidence"]
            if top["suspect_id"] not in identified_ids:
                identified_ids.append(top["suspect_id"])
            log_rows.append({"suspect_id": top["suspect_id"],
                             "name": top["full_name"],
                             "distance": top["distance"], "band": top["band"]})
        elif top:                                   # "possible" band — a lead
            candidate_count += 1
            face["matched_suspect"] = None
            face["confidence"] = top["confidence"]
            log_rows.append({"suspect_id": top["suspect_id"],
                             "name": top["full_name"],
                             "distance": top["distance"], "band": top["band"]})

    identities: dict[str, dict] = {}
    for sid in identified_ids:
        suspect = session.get(Suspect, sid)
        if not suspect:
            continue
        try:
            identities[sid] = await build_identity_dossier(session, suspect, deep=deep)
        except Exception as exc:
            log.warning("identity dossier for %s failed: %s", sid, exc)
            identities[sid] = {"suspect": suspect_to_dict(suspect), "error": str(exc)}

    _log_search(session, analysis, filename, len(faces), len(identified_ids), log_rows)

    return {
        "faces_detected": len(faces),
        "identified": len(identified_ids),
        "candidates": candidate_count,
        "known_people": len(known_names),
        "known_names": known_names,
        "identities": identities,
        "registry": _registry_stats(session),
        "gallery": _gallery_stats(session),
        "summary": _identification_summary(len(faces), identified_ids,
                                           candidate_count, identities, session,
                                           known_names),
    }


def strip_encodings(analysis: dict | None) -> None:
    """Drop raw embeddings from a report that is about to be serialised.

    Any path that returns an analysis to a client must call this (or
    `identify_faces`, which does it as part of matching) — otherwise the 128-d
    biometric vectors ride along in the JSON.
    """
    for face in (((analysis or {}).get("forensics") or {}).get("face_matches") or []):
        face.pop("encoding", None)


async def identify_media(session: Session, payload: dict, *, deep: bool = True,
                         filename: str = "") -> dict:
    """Run identification over an analyze_* payload holding `analysis` and an
    optional `thumbnail` (a video's poster frame).

    Videos carry no faces of their own — the frame does — so identification
    falls through to the thumbnail when the primary analysis has none.
    """
    def n_faces(a: dict | None) -> int:
        return len((((a or {}).get("forensics") or {}).get("face_matches")) or [])

    primary = payload.get("analysis")
    thumb = payload.get("thumbnail")

    if n_faces(primary):
        result = await identify_faces(session, primary, deep=deep,
                                      filename=filename or (primary or {}).get("filename", ""))
        strip_encodings(thumb)
        return result
    if n_faces(thumb):
        result = await identify_faces(session, thumb, deep=deep,
                                      filename=filename or (thumb or {}).get("filename", ""))
        result["from_video_frame"] = True
        strip_encodings(primary)
        return result

    strip_encodings(primary)
    strip_encodings(thumb)
    return await identify_faces(session, primary or {}, deep=deep, filename=filename)


def _identification_summary(n_faces: int, ids: list[str], candidates: int,
                            identities: dict, session: Session,
                            known_names: list[str] | None = None) -> str:
    known = known_names or []
    # The gallery result is stated first when there is no record hit, because
    # "this is Lionel Messi, not on any record" is the useful sentence — not
    # "nobody was identified", which is what this used to say about a face the
    # system could in fact name.
    known_bit = (f"Reference gallery names {'them' if len(known) == 1 else 'them'} as "
                 + ", ".join(known) + "." if known else "")

    if ids:
        names = [identities.get(i, {}).get("suspect", {}).get("full_name", "?")
                 for i in ids]
        s = (f"{len(ids)} of {n_faces} face(s) matched a record: "
             + ", ".join(names) + ".")
        if candidates:
            s += f" {candidates} further face(s) returned a below-threshold lead."
        if known:
            s += " " + known_bit
        return s
    if known:
        s = (f"{known_bit} No criminal record matched"
             + (f", though {candidates} face(s) produced a below-threshold lead."
                if candidates else "."))
        return s
    if candidates:
        return (f"No confirmed identification. {candidates} of {n_faces} face(s) "
                "produced a below-threshold lead — treat as a direction to check, "
                "not an identification.")
    stats = _registry_stats(session)
    gallery = _gallery_stats(session)
    if not stats["enrolled_records"] and not gallery.get("photos"):
        return (f"{n_faces} face(s) detected, but nothing is enrolled to match them "
                f"against — add reference photos to a registry record, or drop "
                f"photos into {gallery.get('directory')}.")
    return (f"{n_faces} face(s) detected; none matched any of the "
            f"{stats['enrolled_records']} enrolled record(s) or the "
            f"{gallery.get('people', 0)} person(s) in the reference gallery.")


def _gallery_stats(session: Session) -> dict:
    """Never raises into a response: a missing/unreadable folder is a reported
    state, not a failed identification request."""
    try:
        return face_gallery.stats(session)
    except Exception as exc:
        log.warning("reference gallery unavailable: %s", exc)
        return {"people": 0, "photos": 0, "error": str(exc)}


def _registry_stats(session: Session) -> dict:
    rows = session.exec(select(Suspect).where(Suspect.active == True)).all()  # noqa: E712
    enrolled = [s for s in rows if (s.face_templates or [])]
    return {
        "active_records": len(rows),
        "enrolled_records": len(enrolled),
        "templates": sum(len(s.face_templates or []) for s in enrolled),
    }


def _log_search(session: Session, analysis: dict, filename: str,
                n_faces: int, n_identified: int, rows: list[dict]) -> None:
    """Chain-of-custody entry for the biometric query itself."""
    try:
        session.add(FaceSearchLog(
            image_sha256=(analysis or {}).get("sha256", ""),
            filename=filename or (analysis or {}).get("filename", ""),
            faces_detected=n_faces,
            identified_count=n_identified,
            results=rows,
        ))
        session.commit()
    except Exception as exc:
        log.warning("face search log failed: %s", exc)
        session.rollback()
