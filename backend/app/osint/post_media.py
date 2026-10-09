# -*- coding: utf-8 -*-
"""Pull the image straight from a post instead of a manual upload.

Two entry points:
  • analyze_from_url(url)   — fetch the post page, discover its image
    (og:image / twitter:image meta tag, or a direct image URL), download the
    bytes and run the full forensic + reverse-source pipeline on them.
  • analyze_from_post(id)   — take a post already in the monitored feed and
    analyze the media it actually carries (the stored attachment URLs, then
    the post's own page). A post with no media says so; nothing is ever
    substituted for it.

Resolution order for a URL: a post we already collected (its stored media),
then the platform's public media route (X → the fxtwitter tweet JSON), then the
page's og:video / og:image preview tags, refetched with a plain bot
User-Agent when the browser one gets a login wall or a 403.

Both return the same shape as the manual upload endpoint (analysis / reverse_image
/ person) plus a `source` block describing where the image came from.
"""
from __future__ import annotations

import json
import logging
import re
from html import unescape
from urllib.parse import urljoin, urlsplit

from sqlmodel import col, select

from app.database import session_scope
from app.models import Post
from app.osint import media_intel
from app.osint.image_analysis import analyze_image, analyze_video
from app.security import ssrf

log = logging.getLogger("sentinel.osint")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
#: Second attempt for pages that wall a browser UA. Instagram serves its
#: og:image preview to a link-preview client but a login page to "Chrome";
#: Wikimedia refuses any client whose UA carries no contact URL.
_BOT_UA = ("SentinelLinkPreview/1.0 "
           "(+https://github.com/thanay2007/E-Rakshak-Sentiment-Analysis)")
_X_STATUS = re.compile(r"^(?:www\.|mobile\.)?(?:x|twitter)\.com$", re.I)
_MAX_BYTES = 25 * 1024 * 1024
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_VID_EXT = (".mp4", ".mov", ".webm", ".m4v", ".3gp", ".mkv", ".avi")
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r'(property|name)\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_CONTENT_RE = re.compile(r'content\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_IMG_META_KEYS = {"og:image", "og:image:url", "og:image:secure_url", "twitter:image",
                  "twitter:image:src"}
_VID_META_KEYS = {"og:video", "og:video:url", "og:video:secure_url",
                  "twitter:player:stream"}


def _extract_og(html: str, base_url: str, keys: set[str]) -> str | None:
    for tag in _META_RE.findall(html):
        key = _ATTR_RE.search(tag)
        content = _CONTENT_RE.search(tag)
        if key and content and key.group(2).lower() in keys:
            # Attribute values are HTML-escaped: a signed CDN URL arrives with
            # `&amp;` between its parameters and 403s unless decoded.
            return urljoin(base_url, unescape(content.group(1)))
    return None


def _extract_og_image(html: str, base_url: str) -> str | None:
    return _extract_og(html, base_url, _IMG_META_KEYS)


async def _fetch(url: str, *, max_bytes: int = _MAX_BYTES,
                 ua: str = _UA) -> ssrf.SafeResponse | None:
    """Guarded GET, redirects revalidated at every hop.

    One retry on a transport error (CDNs time out under load and answer the
    second time), and one retry with the plain bot UA on 401/403/429.

    Returns None on any refusal or transport error — callers here all treat a
    failed fetch as "no media found", and leaking the reason would tell whoever
    supplied the URL what the server can and cannot reach.
    """
    last = None
    for attempt_ua in (ua, ua, _BOT_UA if ua != _BOT_UA else None):
        if attempt_ua is None:
            break
        try:
            _chain, final = await ssrf.safe_chain(
                url, timeout=15.0, headers={"User-Agent": attempt_ua}, max_bytes=max_bytes)
        except ssrf.BlockedRequest:
            log.info("blocked SSRF attempt to %s", url[:200])
            return None
        except Exception:
            continue
        last = final
        if final.status_code not in (401, 403, 429):
            return final
    return last


async def _download_image(url: str) -> tuple[bytes, str] | None:
    r = await _fetch(url)
    if r is None or r.status_code != 200 or not r.content_type.startswith("image/"):
        return None
    name = url.split("/")[-1].split("?")[0] or "post-image"
    return r.content, name


async def _download_video(url: str) -> tuple[bytes, str, bool] | None:
    """Returns (bytes, name, truncated). Accepts video/* or octet-stream."""
    r = await _fetch(url)
    if r is None or r.status_code != 200:
        return None
    ctype = r.content_type
    if not (ctype.startswith("video/") or ctype in ("application/octet-stream", "binary/octet-stream")
            or url.lower().split("?")[0].endswith(_VID_EXT)):
        return None
    name = url.split("/")[-1].split("?")[0] or "post-video"
    return r.content, name, r.truncated


def _candidate_video_urls(url: str) -> list[str]:
    """Direct-download candidates for a video URL. v.redd.it exposes plain
    DASH_<res>.mp4 renditions next to the DASH manifest."""
    low = url.lower().split("?")[0]
    if low.endswith(_VID_EXT):
        return [url]
    if "v.redd.it" in low:
        base = url.split("?")[0].rstrip("/")
        return [f"{base}/DASH_720.mp4", f"{base}/DASH_480.mp4", f"{base}/DASH_360.mp4"]
    return []


def _stored_media(url: str) -> list[str]:
    """Media we already collected for the post at `url`, if it is in the feed."""
    norm = url.split("?")[0].split("#")[0].rstrip("/")
    with session_scope() as s:
        rows = s.exec(select(Post.media_urls).where(
            col(Post.url).in_([norm, norm + "/", url]))).all()
    for media in rows:
        if media:
            return list(media)
    return []


async def _x_media(url: str) -> tuple[list[str], list[str]]:
    """(image URLs, video URLs) of an X/Twitter status, via the public
    fxtwitter tweet JSON — x.com itself serves a JS shell whose og:image is
    X's own logo card, which is not the post's media."""
    parts = urlsplit(url)
    if not _X_STATUS.match(parts.netloc or ""):
        return [], []
    m = re.search(r"/status(?:es)?/(\d+)", parts.path)
    if not m:
        return [], []
    r = await _fetch(f"https://api.fxtwitter.com/status/{m.group(1)}", max_bytes=2_000_000)
    if r is None or r.status_code != 200:
        return [], []
    try:
        media = (json.loads(r.text).get("tweet") or {}).get("media") or {}
    except ValueError:
        return [], []
    images = [p["url"] for p in media.get("photos") or [] if p.get("url")]
    videos = [v["url"] for v in media.get("videos") or [] if v.get("url")]
    images += [v["thumbnail_url"] for v in media.get("videos") or [] if v.get("thumbnail_url")]
    return images, videos


async def _resolve_and_analyze(url: str) -> dict:
    """Try each place the post's real media can come from, in order."""
    stored = _stored_media(url)
    for murl in stored:
        res = await _resolve_page(murl)
        if res.get("ok"):
            res["via"] = "media collected with this post"
            return res

    images, videos = await _x_media(url)
    for vurl in videos:
        dl = await _download_video(vurl)
        if dl:
            data, name, truncated = dl
            thumb = None
            if images:
                tdl = await _download_image(images[-1])
                if tdl:
                    thumb = analyze_image(tdl[0], filename=tdl[1])
            return {"ok": True, "image_url": vurl, "via": "X post video",
                    "analysis": analyze_video(data, filename=name, truncated=truncated),
                    "thumbnail": thumb,
                    **media_intel.report_for_hash((thumb or {}).get("perceptual_hash") or "",
                                                  image_url=vurl)}
    for iurl in images:
        res = await _resolve_page(iurl)
        if res.get("ok"):
            res["via"] = "X post image"
            return res
    if _X_STATUS.match(urlsplit(url).netloc or ""):
        return {"ok": False,
                "reason": "That X post has no image or video, or it is private or deleted."}

    return await _resolve_page(url)


async def _resolve_page(url: str) -> dict:
    """Resolve `url` to its media (image OR video), download it and run the
    full forensic pipeline. For videos the page's preview image (og:image) is
    also analyzed so the perceptual-hash reverse trace still works."""
    image_url, video_url, via = None, None, ""
    page_html = ""

    for cand in _candidate_video_urls(url):
        dl = await _download_video(cand)
        if dl:
            video_url, via = cand, "direct video link"
            data, name, truncated = dl
            break
    else:
        low = url.lower().split("?")[0]
        if low.endswith(_IMG_EXT):
            image_url, via = url, "direct image link"
        else:
            page = await _fetch(url)
            if page is None:
                return {"ok": False,
                        "reason": "That URL could not be fetched. It may be "
                                  "unreachable, or it points into a private "
                                  "network, which is refused."}
            ctype = page.content_type
            if ctype.startswith("image/"):
                image_url, via = page.url, "direct image link"
            elif ctype.startswith("video/"):
                video_url, via = page.url, "direct video link"
                dl = await _download_video(video_url)
                if not dl:
                    return {"ok": False, "reason": "Could not download the video."}
                data, name, truncated = dl
            elif "text/html" in ctype or "<meta" in page.text[:5000].lower():
                page_html = page.text
                if not (_extract_og(page_html, page.url, _VID_META_KEYS)
                        or _extract_og_image(page_html, page.url)):
                    # A login wall or JS shell for a browser; the same page
                    # often carries its preview tags for a link-preview client.
                    retry = await _fetch(url, ua=_BOT_UA)
                    if retry is not None and retry.status_code == 200:
                        page, page_html = retry, retry.text
                vid_meta = _extract_og(page_html, page.url, _VID_META_KEYS)
                if vid_meta:
                    dl = await _download_video(vid_meta)
                    if dl:
                        video_url, via = vid_meta, "og:video tag"
                        data, name, truncated = dl
                if not video_url:
                    image_url = _extract_og_image(page_html, page.url)
                    via = "og:image / preview tag"
            elif page.status_code >= 400:
                return {"ok": False,
                        "reason": f"The site refused the request (HTTP {page.status_code}). "
                                  "It may require login or block automated access."}

    # ── video path: container forensics + thumbnail-based reverse trace ──
    if video_url:
        analysis = analyze_video(data, filename=name, truncated=truncated)
        thumb, thumb_hash = None, ""
        thumb_url = _extract_og_image(page_html, url) if page_html else None
        if thumb_url:
            tdl = await _download_image(thumb_url)
            if tdl:
                thumb = analyze_image(tdl[0], filename=tdl[1])
                thumb_hash = thumb.get("perceptual_hash") or ""
        return {"ok": True, "image_url": video_url, "via": via,
                "analysis": analysis, "thumbnail": thumb,
                **media_intel.report_for_hash(thumb_hash, image_url=video_url)}

    if not image_url:
        return {"ok": False,
                "reason": "No image or video found on the post (no og:image/og:video "
                          "tag). The page may require login or block automated fetches."}
    dl = await _download_image(image_url)
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
        "thumbnail": res.get("thumbnail"),
        "reverse_image": res["reverse_image"],
        "person": res["person"],
    }


def _post_ref(post: Post) -> dict:
    return {"post_id": post.id, "platform": post.platform,
            "author_handle": post.author_handle,
            "text": (post.translation or post.text)[:200],
            "sentiment_label": post.sentiment_label, "url": post.url}


def _has_media(p: Post) -> bool:
    return bool(p.media_urls)


async def analyze_from_post(post_id: str, *, try_live: bool = True) -> dict:
    """Analyze the media a feed post actually carries.

    `post_id` may be a post ID, the post's URL, or blank/"top" for the most
    concerning recent post that has media attached. Only real attachments are
    analyzed — the stored media URLs, then the post's own page. A post with no
    media is reported as such, never resolved to a stand-in image.
    """
    ref_text = (post_id or "").strip()
    with session_scope() as s:
        post = None
        if ref_text and ref_text != "top":
            post = s.get(Post, ref_text)
            if post is None and "://" in ref_text:
                norm = ref_text.split("?")[0].rstrip("/")
                post = s.exec(select(Post).where(
                    col(Post.url).in_([norm, norm + "/", ref_text]))).first()
            if post is None:
                return {"ok": False, "error": "No post with that ID or URL is in the feed."}
        else:
            rows = s.exec(select(Post).where(Post.media_urls != None)  # noqa: E711
                          .order_by(col(Post.created_at).desc()).limit(400)).all()
            rows = [p for p in rows if _has_media(p)]
            rows.sort(key=lambda p: p.concern_score or 0, reverse=True)
            post = rows[0] if rows else None
            if post is None:
                return {"ok": False, "error": "No recent post in the feed has media attached."}
        ref = _post_ref(post)
        url = post.url
        media_urls = list(post.media_urls or [])

    if try_live:
        for murl in media_urls:
            live = await analyze_from_url(murl)
            if live.get("ok"):
                live["source"]["kind"] = "post"
                live["source"]["post"] = ref
                live["source"]["via"] = "media attached to the post"
                return live
        if url:
            live = await analyze_from_url(url)
            if live.get("ok"):
                live["source"]["kind"] = "post"
                live["source"]["post"] = ref
                return live

    if media_urls:
        return {"ok": False, "post": ref,
                "error": "This post's media could not be downloaded — the platform link "
                         "may have expired or been removed. Open the source to view it."}
    return {"ok": False, "post": ref, "error": "This post has no attached image or video."}


def media_posts(limit: int = 24, q: str = "") -> list[dict]:
    """Recent feed posts that carry media — the picker for the live-feed mode."""
    with session_scope() as s:
        stmt = (select(Post).where(Post.media_urls != None)  # noqa: E711
                .order_by(col(Post.created_at).desc()).limit(600))
        rows = [p for p in s.exec(stmt).all() if _has_media(p)]
        if q:
            needle = q.lower().lstrip("@")
            rows = [p for p in rows if needle in (p.author_handle or "").lower()
                    or needle in (p.translation or p.text or "").lower()
                    or needle in (p.location or "").lower()]
        return [{**_post_ref(p), "media_url": (p.media_urls or [""])[0],
                 "media_count": len(p.media_urls or []),
                 "concern_score": round(p.concern_score or 0),
                 "location": p.location or "",
                 "created_at": (p.created_at.isoformat() + "Z") if p.created_at else ""}
                for p in rows[:max(1, min(limit, 60))]]
