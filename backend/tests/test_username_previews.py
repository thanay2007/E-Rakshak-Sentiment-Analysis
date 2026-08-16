# -*- coding: utf-8 -*-
"""Reading Meta's platforms without a session — the "my own Instagram is not found" bug.

Instagram, Threads and Facebook serve a login wall to anything that looks like
a browser, and the page is byte-identical for a real handle and an invented
one. Sherlock's manifest works around that with a third-party mirror
(`imginn.com`), which is dead — so a genuine Instagram handle came back as
"not found", which is the worst answer this console can give: it reads as
evidence of absence.

What they do still publish, to any client that is not pretending to be a
browser, is the link-preview card that chat apps and search engines read. These
tests pin the parsing of that card, and — more importantly — pin the rule that
an unreadable platform is reported as *blocked*, never as "no account".

The live shape of those cards was captured from the real sites; the fixtures
below are trimmed copies, so a change in this parsing shows up here rather than
in an officer's case file.
"""
import asyncio

import httpx
import pytest

from app.osint import username_lookup as ul

IG_CARD = """<html><head>
<meta property="og:title" content="SuratCityPolice (&#064;suratcitypolice) &#x2022; Instagram photos and videos" />
<meta property="og:description" content="448K Followers, 10 Following, 7,269 Posts - See Instagram photos and videos from SuratCityPolice (&#064;suratcitypolice)" />
<meta property="og:image" content="https://scontent.cdninstagram.com/v/t51.2885-19/354457490.jpg" />
</head></html>"""

# What Instagram serves for a handle that does not exist: the app shell, no card.
IG_EMPTY = "<html><head><title>Instagram</title></head><body></body></html>"

THREADS_CARD = """<html><head>
<meta property="og:title" content="National Geographic (&#064;natgeo) &#x2022; Threads, Say more" />
<meta property="og:description" content="18.2M Followers &#x2022; 1.5K Threads &#x2022; Step into wonder with National Geographic. See the latest conversations with &#064;natgeo." />
<meta property="og:image" content="https://cdn.example/natgeo.jpg" />
</head></html>"""

# Threads answers an unknown handle with its own login card, not an empty page.
THREADS_LOGIN = """<html><head>
<meta property="og:title" content="Threads &#x2022; Log in" />
</head></html>"""

# The card the known-good control account serves when the platform is healthy.
CONTROL_CARD = """<html><head>
<meta property="og:title" content="Someone (&#064;someone) &#x2022; profile" />
</head></html>"""

FB_CARD = """<html><head>
<meta property="og:title" content="Surat City Police | Surat" />
<meta property="og:description" content="Surat City Police. 459,212 likes &#xb7; 12,000 talking about this &#xb7; 5,561 were here. Surat City Police is now ONLINE" />
<meta property="og:image" content="https://scontent.fbcdn.net/v/t39.jpg" />
</head></html>"""


@pytest.fixture(autouse=True)
def _fast_and_uncached(monkeypatch):
    """No real backoff sleeps, no Meta pacing gap, no state carried between tests."""
    monkeypatch.setattr(ul, "_PREVIEW_BACKOFF", (0.0, 0.0))
    monkeypatch.setattr(ul, "_META_GAP", 0.0)
    ul._control_cache.clear()
    ul._cooldowns.clear()
    yield
    ul._control_cache.clear()
    ul._cooldowns.clear()


def _read(site: str, url: str, handle: str, body: str, generic: tuple[str, ...],
          status: int = 200, control_body: str | None = None) -> dict:
    """Run one preview read against a fake internet.

    `control_body` is what the platform serves for the known-good account the
    reader falls back on; by default it serves a card, i.e. the platform is
    healthy and a card-less answer for the target really means "no account".
    """
    control_url = ul._PREVIEW_CONTROLS.get(site, "")
    healthy = control_body if control_body is not None else CONTROL_CARD

    def handler(request: httpx.Request) -> httpx.Response:
        if control_url and str(request.url) == control_url:
            return httpx.Response(200, text=healthy)
        return httpx.Response(status, text=body,
                              headers={"content-type": "text/html; charset=utf-8"})

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ul._meta_preview(client, site, url, handle, generic)

    return asyncio.run(run())


def test_instagram_card_yields_a_real_profile():
    row = _read("Instagram", "https://www.instagram.com/suratcitypolice/",
                "suratcitypolice", IG_CARD, ("Instagram",))
    assert row["status"] == "found"
    assert row["source"] == "preview"
    assert row["display_name"] == "SuratCityPolice"
    assert row["followers"] == 448_000
    assert row["avatar"].startswith("https://scontent.cdninstagram.com/")


def test_instagram_without_a_card_is_a_miss():
    row = _read("Instagram", "https://www.instagram.com/nobody_here_9x/",
                "nobody_here_9x", IG_EMPTY, ("Instagram",))
    assert row["status"] == "not_found"


def test_threads_login_card_is_not_a_profile():
    """The trap: Threads answers every unknown handle with a card of its own."""
    row = _read("Threads", "https://www.threads.net/@nobody_here_9x",
                "nobody_here_9x", THREADS_LOGIN, ("Threads • Log in", "Threads"))
    assert row["status"] == "not_found"


def test_threads_card_carries_followers_and_bio():
    row = _read("Threads", "https://www.threads.net/@natgeo", "natgeo",
                THREADS_CARD, ("Threads • Log in", "Threads"))
    assert row["status"] == "found"
    assert row["display_name"] == "National Geographic"
    assert row["followers"] == 18_200_000
    assert row["bio"] == "Step into wonder with National Geographic."


def test_facebook_card_strips_the_boilerplate_counts_from_the_bio():
    row = _read("Facebook", "https://www.facebook.com/suratcitypolice",
                "suratcitypolice", FB_CARD, ("Facebook", "Log in"))
    assert row["status"] == "found"
    assert row["display_name"] == "Surat City Police | Surat"
    assert row["followers"] == 459_212
    assert row["bio"] == "Surat City Police is now ONLINE"


@pytest.mark.parametrize("raw,expected", [
    ("448K", 448_000), ("18.2M", 18_200_000), ("1.5K", 1_500),
    ("459,212", 459_212), ("7,269", 7_269), ("2B", 2_000_000_000),
    ("", None), ("many", None),
])
def test_follower_counts_survive_every_shape_the_cards_use(raw, expected):
    assert ul._count(raw) == expected


def test_an_unreadable_platform_is_blocked_not_absent():
    """The rule the whole module exists for.

    "Not found" is a claim about the world; "blocked" is a claim about the
    lookup. Reporting the first when only the second is true is how an officer
    ends up telling a court that an account does not exist.
    """
    row = _read("Instagram", "https://www.instagram.com/someone/", "someone",
                "", ("Instagram",), status=429)
    assert row["status"] != "not_found"


def test_the_preview_request_does_not_impersonate_a_browser():
    """It asks as itself. A browser UA gets the login wall anyway, and claiming
    to be Googlebot to collect the same public bytes would be a lie."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, text=IG_CARD)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await ul._meta_preview(c, "Instagram", "https://www.instagram.com/x/",
                                   "x", ("Instagram",))

    asyncio.run(run())
    assert seen and "Sentinel" in seen[0]
    assert "Mozilla" not in seen[0] and "Googlebot" not in seen[0]


def test_a_card_less_answer_is_blocked_when_the_platform_serves_nobody():
    """The bug an officer actually hit: a real account reported as not found.

    Meta throttles bursts — after a handful of profile fetches it returns the
    bare app shell, which is byte-identical to what a missing handle returns.
    Asking for an account that certainly exists is the only way to tell the two
    apart, and if that comes back empty too, the honest answer is "we could not
    check", not "there is no account".
    """
    row = _read("Instagram", "https://www.instagram.com/real_person/",
                "real_person", IG_EMPTY, ("Instagram",), control_body=IG_EMPTY)
    assert row["status"] == "blocked"
    assert "not evidence of absence" in row["extra"]["note"]


def test_a_throttled_first_attempt_is_retried_rather_than_believed():
    """One empty answer then a card: the account exists and must be reported so."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(200, text=IG_EMPTY)     # the throttle blip
        return httpx.Response(200, text=IG_CARD)

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ul._meta_preview(c, "Instagram",
                                          "https://www.instagram.com/suratcitypolice/",
                                          "suratcitypolice", ("Instagram",))

    row = asyncio.run(run())
    assert row["status"] == "found"
    assert len(seen) == 2


def test_a_404_is_not_retried():
    """The site's own answer will not change, and three of them is just slower."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(404, text="")

    async def run() -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await ul._meta_preview(c, "Threads", "https://www.threads.net/@x",
                                          "x", ("Threads",))

    row = asyncio.run(run())
    assert row["status"] == "not_found"
    assert len(seen) == 1


def test_an_account_named_after_its_own_platform_still_exists():
    """@instagram on Instagram reported "not found" — for four days it was the
    proof that this reader was broken.

    The card reads "Instagram (@instagram) • Instagram photos and videos", and
    the generic-title check matched it as a *prefix*, so the platform's own
    account — and any handle whose display name starts with the platform's name
    — was declared missing.
    """
    card = """<html><head>
<meta property="og:title" content="Instagram (&#064;instagram) &#x2022; Instagram photos and videos" />
<meta property="og:description" content="695M Followers, 213 Following, 8,090 Posts" />
</head></html>"""
    # This handle *is* the control account, so both URLs serve the same card.
    row = _read("Instagram", "https://www.instagram.com/instagram/", "instagram",
                card, ("Instagram",), control_body=card)
    assert row["status"] == "found"
    assert row["display_name"] == "Instagram"
    assert row["followers"] == 695_000_000


def test_the_platforms_own_fallback_title_is_still_a_miss():
    """The other half: an exact match on the site's own title is not a profile."""
    shell = '<html><head><meta property="og:title" content="Instagram" /></head></html>'
    assert _read("Instagram", "https://www.instagram.com/nobody9x/", "nobody9x",
                 shell, ("Instagram",))["status"] == "not_found"
    login = '<html><head><meta property="og:title" content="Threads &#x2022; Log in" /></head></html>'
    assert _read("Threads", "https://www.threads.net/@nobody9x", "nobody9x",
                 login, ("Threads • Log in", "Threads"))["status"] == "not_found"
