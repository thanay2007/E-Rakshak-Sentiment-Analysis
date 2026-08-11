"""Media proxy — post images and videos, fetched by the server, never the browser.

A post's `media_urls` point at Telegram's, Instagram's and X's own CDNs. Loading
them directly in the console has two problems, and the second is the one that
matters here:

  1. The dashboard's Content-Security-Policy is `img-src 'self' data: blob:`.
     Widening it to a list of CDN hostnames would have to be maintained forever
     and would still be a list of third parties allowed to serve bytes into an
     authenticated police console.
  2. **Every direct load tells that CDN which post an officer is looking at,
     from which IP, and when.** For an OSINT console watching accounts that may
     be run by the people under investigation, that is a live intelligence leak
     out of the investigation — the surveillance target's infrastructure
     learning that it is being surveilled, and roughly from where.

So the server fetches the bytes and the browser only ever talks to this API.
The CDN sees the server, and the CSP stays at `'self'`.

Every fetch goes through `security/ssrf.py`, which is what stops the parameter
from becoming a request forger: a crafted `?url=` pointing at 169.254.169.254,
localhost or an RFC1918 address is rejected before a connection is opened, and
redirects are re-validated per hop rather than followed blindly.

Only image and video content types are served. A URL that answers with HTML or
JSON is refused rather than relayed, because this endpoint's response is
rendered by the browser and an HTML body reflected from `'self'` would be
same-origin script.
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Query, Response

from app.security.ssrf import BlockedRequest, safe_chain

log = logging.getLogger("sentinel.media")
router = APIRouter()

# 12 MB is comfortably above any social-media image and short clip, and well
# under the 25 MB SSRF ceiling. A post whose media exceeds it is not silently
# truncated into a corrupt file — it is refused, and the drawer links out.
MAX_MEDIA_BYTES = 12 * 1024 * 1024

ALLOWED_PREFIXES = ("image/", "video/")
# Everything else is refused. image/svg+xml is excluded deliberately: SVG is a
# scriptable document, and serving one from this origin would hand an attacker
# same-origin script execution inside an authenticated session.
BLOCKED_TYPES = {"image/svg+xml", "image/svg"}


@router.get("/media")
async def proxy_media(url: str = Query(..., min_length=8, max_length=2048)) -> Response:
    """Fetch one image/video by URL and relay the bytes.

    Cached hard: post media is immutable at its URL, the same image is re-viewed
    every time an analyst reopens a post, and each miss costs an outbound
    request that this endpoint exists to minimise.
    """
    try:
        # A browser-ish UA: several CDNs (Telegram's among them) answer a
        # bare client with 403, and a blank image in the drawer is
        # indistinguishable from a post that had no media.
        _, resp = await safe_chain(
            url, max_bytes=MAX_MEDIA_BYTES,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SentinelConsole/1.0)",
                     "Accept": "image/*,video/*;q=0.9,*/*;q=0.5"})
    except BlockedRequest as exc:
        log.warning("media proxy refused %s (%s)", url[:120], exc)
        raise HTTPException(400, f"Refused: {exc}") from exc
    except Exception as exc:
        log.warning("media proxy failed for %s (%s)", url[:120], exc)
        raise HTTPException(502, "Could not fetch the media from its source") from exc

    if resp is None or resp.status_code >= 400:
        raise HTTPException(502, f"Source returned HTTP {resp.status_code if resp else 'no response'}")

    ctype = (resp.content_type or "").split(";")[0].strip().lower()
    if ctype in BLOCKED_TYPES or not ctype.startswith(ALLOWED_PREFIXES):
        raise HTTPException(415, f"Not an image or video ({ctype or 'unknown type'})")
    if resp.truncated:
        raise HTTPException(413, "Media exceeds the size this console will relay")

    return Response(
        content=resp.content,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=86400",
            "ETag": hashlib.sha256(resp.content).hexdigest()[:32],
            # The bytes came from a third party; never let a browser sniff them
            # into something executable.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
