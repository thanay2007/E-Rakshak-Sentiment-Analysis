# -*- coding: utf-8 -*-
"""What the site sweep is allowed to call a hit.

The sweep reads Sherlock's manifest, which records how each of ~480 sites says
"no such user". Getting that reading wrong in either direction is expensive in
a case file: a missed account loses a lead, but a *fabricated* account sends an
officer after a stranger who happens to have squatted the handle nowhere.

Two failure modes are tested here because both were measured against the live
manifest rather than imagined:

  · an error response is not a profile — a 403 bot wall or a host's own 404 has
    no page to search for the "no such user" string, and treating the string's
    absence as a hit is where most upstream false positives come from;
  · a site that answers the same for every handle proves nothing — one site in
    fourteen in this manifest has drifted that way, so every hit is re-run
    against a handle nobody owns and dropped if that one "exists" too.

The network is stubbed: these assert the decision logic, not that some forum is
up today.
"""
import asyncio
import time

import httpx
import pytest

from app.osint import sherlock_sites as sl


def _sweep(manifest: dict, handler, username: str = "suspect_handle", **kw) -> dict:
    """Run a sweep against a fake internet described by `handler`."""
    transport = httpx.MockTransport(handler)

    async def run() -> dict:
        # The sweep opens its own client, so the transport is injected by
        # patching the constructor call it makes.
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real(*args, **kwargs)

        sl.httpx.AsyncClient = factory                 # type: ignore[assignment]
        try:
            return await sl.sweep(username, **kw)
        finally:
            sl.httpx.AsyncClient = real                # type: ignore[assignment]

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def _manifest():
    """Never read the real data.json — each test declares its own sites.

    The exclusions cache is primed empty for the same reason: honouring the
    upstream list means a network fetch, and a test that reaches GitHub is a
    test that fails on a police network with no route out.
    """
    real = sl.load_sites
    real.cache_clear()
    sl._exclusions_cache = (time.monotonic(), set())
    yield
    sl.load_sites = real
    real.cache_clear()
    sl._exclusions_cache = None


def _with_sites(monkeypatch, sites: dict) -> None:
    monkeypatch.setattr(sl, "load_sites", lambda: sites)


MESSAGE_SITE = {
    "Forum": {
        "errorType": "message",
        "errorMsg": "no such member",
        "url": "https://forum.example/u/{}",
        "urlMain": "https://forum.example/",
        "username_claimed": "blue",
    }
}

STATUS_SITE = {
    "Gallery": {
        "errorType": "status_code",
        "url": "https://gallery.example/{}",
        "urlMain": "https://gallery.example/",
        "username_claimed": "blue",
    }
}


def _sites(name: str) -> set[str]:
    return {name}


def test_message_site_hit_is_reported(monkeypatch):
    _with_sites(monkeypatch, MESSAGE_SITE)

    def handler(request: httpx.Request) -> httpx.Response:
        # The control handle gets the miss page; the target gets a profile.
        if "suspect_handle" in str(request.url):
            return httpx.Response(200, text="<title>suspect_handle</title>")
        return httpx.Response(200, text="no such member")

    out = _sweep(MESSAGE_SITE, handler)
    assert out["found"] == 1
    assert [r["site"] for r in out["results"]] == ["Forum"]
    assert out["results"][0]["extra"]["verified"] is True


def test_missing_error_string_on_an_error_response_is_not_a_hit(monkeypatch):
    """A bot wall answers 403 with no profile and no miss-string. Not a find."""
    _with_sites(monkeypatch, MESSAGE_SITE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<h1>Attention Required! | Cloudflare</h1>")

    out = _sweep(MESSAGE_SITE, handler)
    assert out["found"] == 0
    assert out["blocked"] == 1
    assert out["results"][0]["status"] == "blocked"


def test_host_404_with_its_own_wording_is_a_miss(monkeypatch):
    """The site's fingerprint has drifted, but a 404 still means no account."""
    _with_sites(monkeypatch, MESSAGE_SITE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="<title>Profile cannot be displayed</title>")

    out = _sweep(MESSAGE_SITE, handler)
    assert out["found"] == 0
    assert out["not_found"] == 1
    assert out["results"] == []                        # misses are counted, not listed


def test_site_that_answers_the_same_for_everyone_is_discarded(monkeypatch):
    """The drifted-manifest case: every handle 'exists', so no handle does."""
    _with_sites(monkeypatch, MESSAGE_SITE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<title>welcome</title>")

    out = _sweep(MESSAGE_SITE, handler)
    assert out["found"] == 0
    assert out["unreliable"] == 1
    assert out["results"] == []


def test_verification_can_be_switched_off(monkeypatch):
    """Without the control pass the same drifted site reads as a hit.

    Not a feature request — this is the measurement that justifies the extra
    request per hit, kept executable so it cannot quietly stop being true.
    """
    _with_sites(monkeypatch, MESSAGE_SITE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<title>welcome</title>")

    out = _sweep(MESSAGE_SITE, handler, verify=False)
    assert out["found"] == 1


def test_status_code_site_uses_the_code_alone(monkeypatch):
    _with_sites(monkeypatch, STATUS_SITE)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if "suspect_handle" in str(request.url) else 404)

    out = _sweep(STATUS_SITE, handler)
    assert out["found"] == 1
    assert out["results"][0]["http"] == 200


def test_illegal_handle_for_a_site_is_skipped_not_requested(monkeypatch):
    """regexCheck is the site's own rule about what a handle may look like."""
    sites = {
        "Numeric": {
            "errorType": "status_code",
            "regexCheck": "^[0-9]+$",
            "url": "https://numeric.example/{}",
            "urlMain": "https://numeric.example/",
            "username_claimed": "123",
        }
    }
    _with_sites(monkeypatch, sites)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    out = _sweep(sites, handler)
    assert calls == []
    assert out["skipped"] == 1
    assert out["checked"] == 0


def test_nsfw_sites_are_excluded_by_default(monkeypatch):
    sites = {
        "Adult": {
            "errorType": "status_code", "isNSFW": True,
            "url": "https://adult.example/{}", "urlMain": "https://adult.example/",
            "username_claimed": "blue",
        }
    }
    _with_sites(monkeypatch, sites)
    handler = lambda request: httpx.Response(200)      # noqa: E731

    assert _sweep(sites, handler)["checked"] == 0
    assert _sweep(sites, handler, include_nsfw=True)["checked"] == 1


def test_sites_on_sherlocks_exclusion_list_are_never_requested(monkeypatch):
    """Upstream already knows some fingerprints have rotted; skip those.

    The control pass would catch them anyway, but only after spending the
    request — and upstream's list is the accumulated evidence of everyone
    else's false positives, which is worth more than one probe of our own.
    """
    _with_sites(monkeypatch, MESSAGE_SITE)
    sl._exclusions_cache = (time.monotonic(), {"Forum"})
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<title>welcome</title>")

    out = _sweep(MESSAGE_SITE, handler)
    assert calls == []
    assert out["excluded"] == 1
    assert out["results"] == []


def test_the_bundled_exclusion_snapshot_is_readable():
    """The console must still skip the known-bad sites with no route to GitHub."""
    assert len(sl._bundled_exclusions()) > 20


def test_control_handles_are_stable_for_the_same_query():
    """Two officers running the same lookup must discard the same sites."""
    assert sl._control_handles("desh_sachai") == sl._control_handles("DESH_SACHAI")
    assert sl._control_handles("desh_sachai") != sl._control_handles("desh_sachai_1")


def test_no_manifest_is_a_quiet_no_op(monkeypatch):
    """A missing sherlock folder must read as 'not swept', never as 'nothing found'."""
    _with_sites(monkeypatch, {})
    out = _sweep({}, lambda request: httpx.Response(200))
    assert out["results"] == [] and out["checked"] == 0
    assert sl.available() is False
