# -*- coding: utf-8 -*-
"""Pull the image straight from a post instead of a manual upload.

Two entry points:
  • analyze_from_url(url)   — fetch the post page, discover its image
    (og:image / twitter:image meta tag, or a direct image URL), download the
    bytes and run the full forensic + reverse-source pipeline on them.
  • analyze_from_post(id)   — take a post already in the monitored feed and
    resolve its attached media. The simulated stream has no downloadable
    original, so the image is resolved through the monitored-media index; a
    live-API deployment falls through to analyze_from_url on the post's URL.

Both return the same shape as the manual upload endpoint (analysis / reverse_image
/ person) plus a `source` block describing where the image came from.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from sqlmodel import col, select

from app.database import session_scope
from app.models import Post
from app.osint import media_intel
from app.osint.image_analysis import analyze_image

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_MAX_BYTES = 25 * 1024 * 1024
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(property|name)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_CONTENT_RE = re.compile(r'content\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_IMG_META_KEYS = {"og:image", "og:image:url", "og:image:secure_url", "twitter:image",
                  "twitter:image:src"}


def _extract_og_image(html: str, base_url: str) -> str | None:
    for tag in _META_RE.findall(html):
        key = _ATTR_RE.search(tag)
        content = _CONTENT_RE.search(tag)
        if key and content and key.group(2).lower() in _IMG_META_KEYS:
            return urljoin(base_url, content.group(1))
    return None


async def _download_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    r = await client.get(url, headers={"User-Agent": _UA})
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or not ctype.startswith("image/"):
        return None
    data = r.content[:_MAX_BYTES]
    name = url.split("/")[-1].split("?")[0] or "post-image"
    return data, name


async def _resolve_and_analyze(url: str) -> dict:
    """Resolve `url` to an image, download it and run the full pipeline."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        image_url, via = None, ""
        # direct image link?
        low = url.lower().split("?")[0]
        if low.endswith(_IMG_EXT):
            image_url, via = url, "direct image link"
        else:
            page = await client.get(url, headers={"User-Agent": _UA})
            ctype = page.headers.get("content-type", "")
            if ctype.startswith("image/"):
                image_url, via = str(page.url), "direct image link"
            elif "text/html" in ctype or "<meta" in page.text[:5000].lower():
                image_url = _extract_og_image(page.text, str(page.url))
                via = "og:image / preview tag"
        if not image_url:
            return {"ok": False,
                    "reason": "No image found on the post (no og:image / preview tag). "
                              "The page may require login or block automated fetches."}
        dl = await _download_image(client, image_url)
        if not dl:
            return {"ok": False, "reason": f"Could not download the post image ({image_url})."}
        data, name = dl
        analysis = analyze_image(data, filename=name)
        phash = analysis.get("perceptual_hash")
        return {"ok": True, "image_url": image_url, "via": via, "analysis": analysis,
                **media_intel.report_for_hash(phash or "", image_url=image_url)}


async def analyze_from_url(url: str) -> dict:
    url = (url or "").strip()
    if not url or "." not in url:
        return {"ok": False, "error": "Enter a valid post or image URL."}
    if "://" not in url:
        url = "https://" + url
    try:
        res = await _resolve_and_analyze(url)
    except Exception as exc:
        return {"ok": False, "error": f"Fetch failed ({type(exc).__name__}). "
                                      f"The host may be offline or blocking the request."}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("reason", "Could not resolve an image.")}
    return {
        "ok": True,
        "source": {"kind": "url", "post_url": url, "image_url": res["image_url"], "via": res["via"]},
        "analysis": res["analysis"],
        "reverse_image": res["reverse_image"],
        "person": res["person"],
    }


def _post_ref(post: Post) -> dict:
    return {"post_id": post.id, "platform": post.platform,
            "author_handle": post.author_handle,
            "text": (post.translation or post.text)[:200],
            "threat_label": post.threat_label, "url": post.url}


async def analyze_from_post(post_id: str, *, try_live: bool = True) -> dict:
    """Resolve the media attached to a feed post."""
    with session_scope() as s:
        post = s.get(Post, post_id) if post_id and post_id != "top" else None
        if not post:
            # convenience: newest post that carries media in the index
            rows = s.exec(select(Post).order_by(col(Post.threat_score).desc()).limit(120)).all()
            post = next((p for p in rows
                         if media_intel.scenario_for(p.id, p.threat_label)), rows[0] if rows else None)
        if not post:
            return {"ok": False, "error": "No posts available in the feed."}
        ref = _post_ref(post)
        pid, label, url = post.id, post.threat_label, post.url

    # A real platform URL (news/RSS/Web) may expose a public og:image — try it.
    if try_live and url and any(url.lower().split("?")[0].endswith(e) for e in _IMG_EXT):
        live = await analyze_from_url(url)
        if live.get("ok"):
            live["source"]["kind"] = "post"
            live["source"]["post"] = ref
            return live

    # Simulated feed: resolve the attached image via the monitored-media index.
    scenario = media_intel.scenario_for(pid, label)
    if not scenario:
        return {"ok": False, "post": ref,
                "error": "This post has no attached image/video."}
    phash = scenario["hash"]
    bundle = media_intel.report_for_hash(phash)
    return {
        "ok": True,
        "source": {"kind": "post", "post": ref, "via": "monitored-media index",
                   "note": "Simulated feed has no downloadable original — the post's "
                           "image was resolved through SENTINEL's monitored-media index."},
        "analysis": {
            "filename": f"{ref['platform'].lower()}_{pid}.jpg",
            "media_type": "image", "resolved_from_index": True,
            "perceptual_hash": phash, "subject": scenario["subject"],
            "manipulation": {"integrity_score": None, "findings": [
                {"level": "info", "text": "Image resolved from the monitored-media index; "
                                          "pixel-level forensics need the original file."}]},
        },
        "reverse_image": bundle["reverse_image"],
        "person": bundle["person"],
    }
