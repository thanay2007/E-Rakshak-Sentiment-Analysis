# -*- coding: utf-8 -*-
"""Google Lens reverse-image search — run for the analyst, not linked to.

The Reverse-Source Trace used to end at four "continue your search here"
buttons. That is the wrong place to stop: the question an officer has is "where
else has this photo been posted", and handing back a link to Google Lens leaves
them to answer it by hand, on their own browser, with their own IP address
touching every page the photo appears on. This module answers it instead and
returns the pages.

How, given Lens has no API:

  1. The image is POSTed to `lens.google.com/v3/upload`, which is the same
     multipart request the browser's own "search by image" makes. It answers 303
     with the results URL.
  2. That page is JavaScript-rendered, so it is opened in a headless Chrome —
     the same Selenium dependency the Facebook collector already needs — and the
     visual-match cards are read out of the rendered DOM.

Step 1 is done inside the browser rather than with an HTTP client, because the
results URL is bound to the session that uploaded it: fetching it with a
different cookie jar returns 403.

Two practical notes, both learned the hard way and both load-bearing:

  • Chrome runs against a PERSISTENT profile directory. A fresh profile every
    run is a brand-new browser every run, and Google answers that with its
    "unusual traffic" interrogation page instead of results.
  • Exactly one search runs at a time (a process-wide lock) and results are
    cached by image hash. This is a courtesy to Google as much as a performance
    measure — a console that fired parallel headless browsers at them would be
    blocked, permanently and deservedly.

Everything degrades to the old behaviour: with Selenium absent, Chrome missing,
or Google serving a challenge, the result carries `ok: false` and a plain reason,
and the caller still shows the manual engine links. It never raises.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

#: One browser at a time, process-wide.
_lock = threading.Lock()
#: sha256 -> (monotonic_time, result)
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600.0
_CACHE_MAX = 64

#: Google's own hosts are the search UI, not results.
_SKIP_HOSTS = ("google.", "gstatic.com", "googleusercontent.com", "youtube.com/redirect",
               "policies.google", "support.google", "accounts.google")


def available() -> tuple[bool, str]:
    """Whether an automatic search can be attempted at all."""
    if not settings.LENS_ENABLED:
        return False, "Automatic reverse-image search is switched off (LENS_ENABLED)."
    try:
        import selenium  # noqa: F401
    except Exception:
        return False, ("Selenium is not installed, so the browser-driven search "
                       "cannot run. `pip install selenium` and make sure Chrome "
                       "is on this machine.")
    return True, ""


# ── the browser ────────────────────────────────────────────────────────────

def _driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    profile = Path(settings.LENS_PROFILE_DIR)
    profile.mkdir(parents=True, exist_ok=True)

    opts = Options()
    if settings.LENS_HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,1600")
    # The profile is the whole anti-challenge story — see the module docstring.
    opts.add_argument(f"--user-data-dir={profile}")
    opts.add_argument(f"--user-agent={_UA}")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(settings.LENS_TIMEOUT)
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"})
    except Exception:
        pass
    return driver


def _warm_marker() -> Path:
    return Path(settings.LENS_PROFILE_DIR) / ".sentinel-warm"


def _warm(driver) -> None:
    """Give a brand-new profile an ordinary browsing history before it uploads.

    A profile with no cookies that opens Google and immediately posts an image
    is exactly the shape of a scraper, and Google answers it with the "unusual
    traffic" page. One consent acceptance and one plain text search is enough to
    look like a browser instead; after that the profile carries the cookies and
    this never runs again.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    try:
        driver.get("https://www.google.com/ncr")
        time.sleep(2.0)
        # Consent interstitial, where it is served.
        for label in ("Accept all", "I agree", "Reject all"):
            buttons = driver.find_elements(
                By.XPATH, f"//button[normalize-space(.)='{label}']")
            if buttons:
                try:
                    buttons[0].click()
                    time.sleep(1.5)
                except Exception:
                    pass
                break
        boxes = driver.find_elements(By.CSS_SELECTOR, "textarea[name=q], input[name=q]")
        if boxes:
            boxes[0].send_keys("gujarat news" + Keys.RETURN)
            time.sleep(2.5)
        _warm_marker().parent.mkdir(parents=True, exist_ok=True)
        _warm_marker().write_text("warmed", encoding="utf-8")
    except Exception as exc:
        log.info("lens profile warm-up did not complete: %s", exc)


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _collect(driver, limit: int) -> list[dict]:
    """Read the result cards out of the rendered page.

    Deliberately structural rather than class-based: Google's class names are
    generated and change without notice, but "an anchor to another site, with
    text" has described a search result for twenty-five years. The source is
    taken from the URL's own domain rather than the card's label, which is the
    one part of a result that cannot be styled away.
    """
    from selenium.webdriver.common.by import By

    out: list[dict] = []
    seen: set[str] = set()
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='http']"):
        try:
            href = a.get_attribute("href") or ""
            host = urlparse(href).netloc
            if not host or any(s in href for s in _SKIP_HOSTS):
                continue
            if href in seen:
                continue
            text = " ".join((a.text or "").split())
            if not text:
                continue
            seen.add(href)

            domain = _domain(href)
            title = text
            # Cards render as "<source>\n<title>"; the source is repeated in the
            # domain, so strip it off the front rather than showing it twice.
            label = domain.split(".")[0].lower()
            if title.lower().startswith(label) and len(title) > len(label) + 2:
                title = title[len(label):].lstrip(" .·|-")
            out.append({"title": title[:200], "url": href, "domain": domain})
            if len(out) >= limit:
                break
        except Exception:
            continue
    return out


def _challenged(driver) -> bool:
    url = (driver.current_url or "").lower()
    if "/sorry/" in url or "consent." in url:
        return True
    try:
        from selenium.webdriver.common.by import By
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return False
    return "unusual traffic" in body or "not a robot" in body


def _search_blocking(data: bytes, filename: str) -> dict:
    """One full Lens round-trip. Runs on a worker thread; never raises."""
    import tempfile

    from selenium.webdriver.common.by import By

    started = time.monotonic()
    suffix = Path(filename).suffix.lower() or ".jpg"
    if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        suffix = ".jpg"

    tmp = Path(tempfile.gettempdir()) / f"sentinel-lens-{int(time.time()*1000)}{suffix}"
    tmp.write_bytes(data)
    driver = None
    try:
        driver = _driver()
        if not _warm_marker().exists():
            _warm(driver)
        driver.get("https://www.google.com/imghp?hl=en&gl=in")
        time.sleep(1.5)

        cams = driver.find_elements(By.CSS_SELECTOR, "[aria-label*='by image' i]")
        if cams:
            try:
                cams[0].click()
                time.sleep(1.2)
            except Exception:
                pass
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type=file]")
        if not inputs:
            return {"ok": False, "reason": "Google's image-search upload control "
                                           "did not load."}
        inputs[-1].send_keys(str(tmp))

        deadline = started + settings.LENS_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(1.0)
            url = driver.current_url or ""
            if "vsrid" in url or "/sorry/" in url:
                break
        if _challenged(driver):
            # Drop the warm marker so the next attempt rebuilds the profile's
            # browsing history rather than walking straight back into the same
            # challenge with the same cookies.
            try:
                _warm_marker().unlink()
            except OSError:
                pass
            return {"ok": False, "challenged": True,
                    "reason": "Google served an anti-automation check instead of "
                              "results — usually because this network has run "
                              "several searches in quick succession. It clears on "
                              "its own; the manual engine links below still work."}
        if "vsrid" not in (driver.current_url or ""):
            return {"ok": False, "reason": "Google Lens did not return a results "
                                           "page in time."}

        # Cards stream in after the URL settles; a fixed pause here is worth more
        # than a selector wait because there is no stable selector to wait on.
        time.sleep(settings.LENS_SETTLE_SECONDS)
        matches = _collect(driver, settings.LENS_MAX_RESULTS)

        domains: list[str] = []
        for m in matches:
            if m["domain"] and m["domain"] not in domains:
                domains.append(m["domain"])

        return {
            "ok": True,
            "engine": "Google Lens",
            "matches": matches,
            "match_count": len(matches),
            "domains": domains,
            "results_url": driver.current_url,
            "took_seconds": round(time.monotonic() - started, 1),
        }
    except Exception as exc:
        log.warning("lens search failed: %s", exc)
        return {"ok": False, "reason": f"The reverse-image search could not run: {exc}"}
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        try:
            tmp.unlink()
        except OSError:
            pass


# ── public entry point ─────────────────────────────────────────────────────

def _cached(sha: str) -> dict | None:
    hit = _cache.get(sha)
    if not hit:
        return None
    if (time.monotonic() - hit[0]) > _CACHE_TTL:
        _cache.pop(sha, None)
        return None
    return {**hit[1], "cached": True}


async def search(data: bytes, *, filename: str = "") -> dict:
    """Reverse-search one image and return what Google Lens actually found.

    Cached by image content: re-opening the same evidence, or two officers
    looking at the same post, costs one search rather than one each.
    """
    sha = hashlib.sha256(data).hexdigest()
    hit = _cached(sha)
    if hit:
        return hit

    ok, why = available()
    if not ok:
        return {"ok": False, "reason": why}

    import asyncio

    def run() -> dict:
        # Serialised deliberately: parallel headless browsers against Google is
        # how a deployment gets itself blocked.
        with _lock:
            again = _cached(sha)
            if again:
                return again
            return _search_blocking(data, filename)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run),
            timeout=settings.LENS_TIMEOUT + settings.LENS_SETTLE_SECONDS + 45)
    except asyncio.TimeoutError:
        return {"ok": False, "reason": "The reverse-image search timed out."}

    if result.get("ok"):
        if len(_cache) >= _CACHE_MAX:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[sha] = (time.monotonic(), result)
    return result
