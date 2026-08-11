# -*- coding: utf-8 -*-
"""Re-analyse posts already in the database with the current pipeline.

Why this exists. The scoring formula and the label taxonomy changed: rows
collected before the change carry a `concern_score` computed by the retired
threat-severity formula and a `sentiment_label` from the old two-model
ensemble, with no evidence trail behind either. Left alone, the console would
aggregate two incompatible scales in one chart and every historical post would
open with an empty evidence panel — the number on screen would mean one thing
for yesterday's posts and another for today's, with nothing marking the seam.

So the corpus is re-analysed in place. Each post is replayed through
`enrich_batch` exactly as if it had just been collected, using the text and
account metadata already on the row.

What this does NOT redo, deliberately:
  • **Translation** is preserved. It is already on the row, it costs an LLM
    call, and nothing about it changed.
  • **News corroboration** is preserved for the same reason — re-querying 7,000
    posts would blow through both daily API budgets in one run, and the stored
    result is what was true when the post was live.
  • **The Groq final check** is not re-run (it is a network call per batch and
    this is a bulk offline job). Rows therefore come out with the three local
    models' verdict; the evidence trail says exactly that, so nothing claims a
    review that did not happen.

Alerts are NOT re-raised. An alert is a record that an officer was notified at
a point in time; manufacturing new ones for old posts would put events in the
log that never occurred. Existing alerts keep their original score, which is
why `alert.concern_score` is left alone too.

Usage (from backend/):
    python -m app.ml.rescore                # everything not yet re-analysed
    python -m app.ml.rescore --all          # force, including already-done rows
    python -m app.ml.rescore --limit 500    # a slice, to sanity-check first
    python -m app.ml.rescore --batch 128
"""
from __future__ import annotations

import argparse
import time

from sqlalchemy import String, cast
from sqlmodel import col, select

from app.database import session_scope
from app.models import Post
from app.schemas import RawPost


def _to_raw(p: Post) -> RawPost:
    """Rebuild the collector's-eye view of a stored post."""
    return RawPost(
        platform=p.platform,
        author_handle=p.author_handle,
        author_id=p.author_id,
        author_name=p.author_name,
        author_followers=p.author_followers,
        author_verified=p.author_verified,
        author_account_age_days=p.author_account_age_days,
        text=p.text,
        translation=p.translation,
        hashtags=p.hashtags or [],
        location=p.location,
        latitude=p.latitude,
        longitude=p.longitude,
        engagement=p.engagement or {},
        url=p.url,
        media_urls=p.media_urls or [],
        cluster_id=p.cluster_id,
        is_amplified=p.is_amplified,
        true_label=p.true_label,
        created_at=p.created_at,
    )


def rescore(batch_size: int = 100, limit: int | None = None,
            force: bool = False, verbose: bool = True) -> dict:
    """Replay stored posts through the current pipeline. Returns a summary."""
    from app.ml.pipeline import attach_evidence, get_pipeline

    pipeline = get_pipeline()
    if verbose:
        print(f"Re-analysing with NLP_MODE={pipeline.mode}")

    # Selecting the work is one query, not one query per row. The obvious
    # version — fetch every id, then load each row to inspect its consensus —
    # is 7,000 round trips to a hosted database and takes minutes before any
    # actual work starts. The JSON column is cast to text and matched instead,
    # which is portable across SQLite and Postgres (the column is JSON, not
    # JSONB, so the `?` containment operator is not available here).
    with session_scope() as s:
        stmt = select(Post.id)
        if not force:
            stmt = stmt.where(
                cast(Post.sentiment_consensus, String).notlike("%\"evidence\"%")
            )
        stmt = stmt.order_by(col(Post.created_at).desc())
        if limit:
            stmt = stmt.limit(limit)
        ids = list(s.exec(stmt).all())

    if not ids:
        if verbose:
            print("Nothing to do — every post already carries an evidence trail.")
        return {"scanned": 0, "updated": 0, "changed_label": 0}

    t0 = time.time()
    updated = changed = 0
    for i in range(0, len(ids), batch_size):
        chunk = ids[i:i + batch_size]
        with session_scope() as s:
            # one SELECT ... IN (...) per batch, not one per post
            rows = list(s.exec(select(Post).where(col(Post.id).in_(chunk))).all())
            if not rows:
                continue
            enriched = pipeline.enrich_batch([_to_raw(r) for r in rows])
            for row, nlp in zip(rows, enriched):
                attach_evidence(nlp)
                before = row.sentiment_label
                row.sentiment_label = nlp["sentiment_label"]
                row.sentiment_score = nlp["sentiment_score"]
                row.sentiment_confidence = nlp["sentiment_confidence"]
                row.sentiment_consensus = nlp["sentiment_consensus"]
                row.class_probs = nlp["class_probs"]
                row.concern_score = nlp["concern_score"]
                row.toxicity_score = nlp["toxicity_score"]
                row.hate_flags = nlp["hate_flags"]
                row.intent = nlp["intent"]
                row.keywords = nlp["keywords"]
                row.language = nlp["language"]
                row.code_mixed = nlp["code_mixed"]
                # translation and fact_check are left exactly as they were
                s.add(row)
                updated += 1
                if before != row.sentiment_label:
                    changed += 1
            s.commit()
        if verbose:
            done = min(i + batch_size, len(ids))
            rate = done / max(time.time() - t0, 0.001)
            print(f"  {done}/{len(ids)} posts · {rate:.0f}/s · "
                  f"{changed} tags changed", end="\r")

    elapsed = time.time() - t0
    if verbose:
        print(f"\nRe-analysed {updated} posts in {elapsed:.1f}s "
              f"({changed} changed tag).")
    return {"scanned": len(ids), "updated": updated, "changed_label": changed,
            "elapsed_seconds": round(elapsed, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--limit", type=int, default=None,
                    help="only the N most recent matching posts")
    ap.add_argument("--all", action="store_true", dest="force",
                    help="re-analyse every post, including already-current ones")
    args = ap.parse_args()
    rescore(batch_size=args.batch, limit=args.limit, force=args.force)


if __name__ == "__main__":
    main()
