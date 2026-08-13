"""Instagram's logged-out web routes — collection with no account at all.

Every other Instagram path in this project needs a session, and a session is
the part that keeps failing: the account gets checkpointed, the cookie is
revoked, the password goes stale, and Instagram quietly withholds the
discovery endpoints (tags/, fbsearch/, locations/) from accounts it does not
trust. Each of those is a day or a week with a green light on the dashboard and
nothing whatsoever collected from Instagram.

This module is the floor under that. It calls the routes instagram.com itself
serves to a signed-out browser, so it holds no credential and cannot be logged
out. The field name Instagram returns says exactly what it is —
`xig_logged_out_popular_search_media_info`.

Discovered from instagram4j (github.com/instagram4j/instagram4j, Apache-2.0),
whose web module is built on these routes; the request shapes, the GraphQL
document ids and the response envelopes are its findings, verified live here
before being written down. Its Java is not vendored — it has no location
support, its authenticated paths failed against the same session that works
here, and a JVM in a Python ingest loop would cost more than the two requests
this file makes.

What it can do:
  * **hashtag media** — the one that matters. #surat, #rajkot, #અમદાવાદ:
    twenty-nine posts an ask, from whoever is posting them, which is the
    ordinary-resident traffic a seed roster of civic pages never contains.
  * **profile** and **user media** for a public account, by name.

What it cannot do: comments, locations, follower counts on hashtag results, or
anything private. It is a floor, not a replacement — a live session still
collects more, and this keeps the platform contributing while there isn't one.

Rate limits are real and per-IP: `users/web_profile_info` starts answering 429
after a handful of calls, while the GraphQL routes tolerate far more. A 429 is
therefore raised as its own error so callers can park the route rather than
retry into a longer block.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests

from app.crawlers.common import extract_hashtags
from app.schemas import RawPost

log = logging.getLogger("sentinel.crawlers")

#: GraphQL document ids. These are Instagram's, they rotate without notice, and
#: a retired one answers "The GraphQL document with ID ... was not found" —
#: which is why every caller here treats failure as normal rather than fatal.
DOC_HASHTAG_MEDIA = "33897670563213924"
DOC_USER_POSTS = "7950326061742207"

#: The signed-out browser's own headers. The user agent is Instagram's mobile
#: web string: the desktop one is served the login wall far sooner.
_HEADERS = {
    "authority": "www.instagram.com",
    "accept": "application/json",
    "origin": "https://www.instagram.com",
    "referer": "https://www.instagram.com/",
    "content-type": "application/x-www-form-urlencoded",
    "user-agent": "Instagram 347.3.0.41.106",
}
TIMEOUT = 25


class PublicRateLimited(RuntimeError):
    """Instagram answered 429. The caller should stop asking for a while."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def _graphql(session: requests.Session, doc_id: str, variables: dict,
             url: str = "https://www.instagram.com/api/graphql") -> dict:
    response = session.post(
        url,
        data={"doc_id": doc_id, "variables": json.dumps(variables), "lsd": "sentinel"},
        headers={"x-fb-lsd": "sentinel"}, timeout=TIMEOUT)
    if response.status_code == 429:
        raise PublicRateLimited("Instagram rate-limited the logged-out route")
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors") and payload.get("data") is None:
        raise RuntimeError(str(payload["errors"])[:200])
    return payload.get("data") or payload


def _caption(node: dict) -> str:
    """Hashtag results carry the caption inline; profile media nest it in an
    edge list. One helper so both shapes land in the same field."""
    caption = node.get("caption")
    if isinstance(caption, dict):
        return caption.get("text", "") or ""
    edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    return (edges[0].get("node", {}).get("text", "") if edges else "") or ""


def _taken_at(node: dict) -> datetime | None:
    stamp = node.get("taken_at_timestamp") or node.get("taken_at")
    if not stamp:
        return None
    try:
        return datetime.fromtimestamp(int(stamp), tz=timezone.utc).replace(tzinfo=None)
    except (ValueError, OSError, OverflowError):
        return None


def _media_url(node: dict) -> list[str]:
    for key in ("display_uri", "display_url", "thumbnail_src"):
        if (url := node.get(key)):
            return [str(url)]
    versions = node.get("video_versions") or []
    return [str(versions[0]["url"])] if versions else []


def _to_post(node: dict, city: str, handle: str = "", followers: int = 0,
             verified: bool = False, name: str = "") -> tuple[str, RawPost] | None:
    """(media id, RawPost), or None when there is no text to score."""
    text = _caption(node).strip()
    if not text:
        return None
    user = node.get("user") or node.get("owner") or {}
    handle = handle or user.get("username") or "instagram"
    code = node.get("code") or node.get("shortcode") or ""
    likes = node.get("like_count")
    if likes is None:
        likes = (node.get("edge_liked_by") or node.get("edge_media_preview_like")
                 or {}).get("count", 0)
    comments = node.get("comment_count")
    if comments is None:
        comments = (node.get("edge_media_to_comment") or {}).get("count", 0)
    return str(node.get("id") or code), RawPost(
        platform="Instagram",
        author_handle=handle,
        author_id=str(user.get("id") or user.get("pk") or ""),
        author_name=name or user.get("full_name", "") or handle,
        # A logged-out hashtag result carries no follower count at all. 0 is
        # honest here — the amplification score reads it as unknown reach
        # rather than as a claim that nobody follows this account.
        author_followers=followers,
        author_verified=verified or bool(user.get("is_verified")),
        text=text[:1000],
        hashtags=extract_hashtags(text),
        location=city,
        engagement={"likes": int(likes or 0), "shares": 0,
                    "comments": int(comments or 0),
                    "views": int(node.get("play_count") or 0)},
        url=f"https://www.instagram.com/p/{code}/" if code else "",
        media_urls=_media_url(node),
        created_at=_taken_at(node),
    )


def hashtag_medias(tag: str, limit: int = 29,
                   session: requests.Session | None = None) -> list[tuple[str, RawPost]]:
    """Recent public media for one tag, signed out.

    The city is left empty on purpose: a tag says the post is on-scope, not
    where it was written, and ingestion's geo enrichment reads the text.
    """
    session = session or _session()
    data = _graphql(session, DOC_HASHTAG_MEDIA,
                    {"after": None, "media_count": max(1, limit),
                     "keyword": tag.lstrip("#")})
    edges = (data.get("xig_logged_out_popular_search_media_info") or {}).get("edges") or []
    out = []
    for edge in edges:
        if (post := _to_post(edge.get("node") or {}, "")):
            out.append(post)
    return out


def profile(username: str,
            session: requests.Session | None = None) -> dict | None:
    """Public profile fields, or None when Instagram will not serve them.

    This is the route that rate-limits hardest — a handful of calls per IP and
    it starts answering 429 — so callers should treat it as a bonus rather
    than a dependency.
    """
    session = session or _session()
    response = session.get("https://www.instagram.com/api/v1/users/web_profile_info/",
                           params={"username": username}, timeout=TIMEOUT)
    if response.status_code == 429:
        raise PublicRateLimited("Instagram rate-limited web_profile_info")
    if response.status_code != 200 or not response.text.startswith("{"):
        return None
    user = (response.json().get("data") or {}).get("user")
    if not user:
        return None
    return {
        "pk": str(user.get("id") or ""),
        "username": user.get("username") or username,
        "full_name": user.get("full_name") or "",
        "followers": int((user.get("edge_followed_by") or {}).get("count", 0)),
        "verified": bool(user.get("is_verified")),
        "is_private": bool(user.get("is_private")),
        # The profile payload already carries the first page of media, so a
        # caller that wants both pays for one request rather than two.
        "medias": [e.get("node") or {} for e in
                   (user.get("edge_owner_to_timeline_media") or {}).get("edges", [])],
    }


def user_medias(pk: str, limit: int = 12,
                session: requests.Session | None = None) -> list[dict]:
    """Recent media for a public account by numeric id, signed out."""
    session = session or _session()
    data = _graphql(session, DOC_USER_POSTS, {"id": str(pk), "first": limit},
                    url="https://www.instagram.com/graphql/query")
    edges = ((data.get("user") or {}).get("edge_owner_to_timeline_media") or {}).get("edges", [])
    return [e.get("node") or {} for e in edges]


def account_medias(username: str, city: str = "", limit: int = 12,
                   session: requests.Session | None = None
                   ) -> list[tuple[str, RawPost]]:
    """Posts from one public account, signed out — profile then timeline."""
    session = session or _session()
    info = profile(username, session)
    if info is None or info["is_private"]:
        return []
    nodes = info["medias"][:limit]
    if not nodes and info["pk"]:
        nodes = user_medias(info["pk"], limit, session)
    out = []
    for node in nodes:
        post = _to_post(node, city, handle=info["username"],
                        followers=info["followers"], verified=info["verified"],
                        name=info["full_name"])
        if post:
            out.append(post)
    return out
