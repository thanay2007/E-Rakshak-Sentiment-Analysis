"""One-time interactive Facebook login — writes backend/fb_cookies.json.

    cd backend && python -m app.crawlers.facebook_login          # log in
    cd backend && python -m app.crawlers.facebook_login --verify # prove it works

Facebook answers an automated login from an unfamiliar IP with a checkpoint: a
code by email or SMS, a "was this you?" device confirmation, sometimes a 2FA
prompt on top. Answering one needs a screen. The ingestion loop has none — it
would just see the login fail every cycle — so the handshake happens here once
in a *visible* browser, and the collector reuses the saved cookie jar
afterwards.

With FB_EMAIL/FB_PASSWORD in .env the form is filled in for you; without them,
log in by hand in the window that opens. Either way the tool waits until
Facebook actually hands out a session, so clearing a checkpoint mid-way is
fine. Press Enter when you are done and the cookies are written.

The jar is written to a file and never printed: it is full account access with
no further prompt, exactly like the Instagram session dump. It is in
.gitignore; treat a copy of it as a live credential.

--verify does a small live read (one seed page, a handful of posts) so a
deployment can be confirmed end to end without waiting for a crawl tick.

Use a dedicated account, never a personal one — this traffic can get an account
rate-limited or disabled.
"""
import sys
import time

from app.config import settings
from app.crawlers.facebook_scrape import COOKIES_FILE, FacebookScrapeCollector

# A Windows console defaults to cp1252, which cannot encode a single Gujarati
# or Devanagari character — so printing a real Surat post would kill this tool
# on exactly the content it exists to prove works.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

LOGIN_WAIT_SECONDS = 300


def login() -> None:
    collector = FacebookScrapeCollector()
    # Visible on purpose: this command exists precisely for the steps that
    # cannot be completed without a human looking at the page.
    original_headless = settings.FB_SCRAPE_HEADLESS
    settings.FB_SCRAPE_HEADLESS = False
    try:
        driver = collector._build_driver()
    finally:
        settings.FB_SCRAPE_HEADLESS = original_headless

    try:
        if settings.FB_EMAIL and settings.FB_PASSWORD:
            print(f"Logging in as {settings.FB_EMAIL} ...")
            try:
                collector._password_login(driver)
            except Exception as exc:
                print(f"Automated login stopped: {exc}")
        else:
            print("No FB_EMAIL/FB_PASSWORD set — log in by hand in the browser "
                  "window.")
            driver.get("https://www.facebook.com/login")

        print("\nComplete any checkpoint or 2FA prompt in the browser window.")
        deadline = time.monotonic() + LOGIN_WAIT_SECONDS
        while time.monotonic() < deadline:
            if collector._logged_in(driver):
                break
            time.sleep(3)
        else:
            raise SystemExit(
                f"No session after {LOGIN_WAIT_SECONDS}s — Facebook never set a "
                "c_user cookie. Nothing was written.")

        collector._save_cookies(driver)
        account = next((c["value"] for c in driver.get_cookies()
                        if c["name"] == "c_user"), "?")
        print(f"\nLogged in — account id {account}.")
        print(f"Cookies written to {COOKIES_FILE}. They were not printed: they "
              "are full account access. Revoke them any time from Facebook > "
              "Settings > Security > Where you're logged in, then re-run this.")
        print("\nThe 'Facebook (browser)' collector will pick them up on the "
              "next API start — no further configuration needed.")
    finally:
        driver.quit()


def verify() -> None:
    """One real seed page, read through the adapter's own path."""
    if not COOKIES_FILE.exists() and not (settings.FB_C_USER and settings.FB_XS):
        raise SystemExit("No session yet — run without --verify first.")
    if not settings.FB_PAGE_IDS:
        raise SystemExit('No seed pages — set FB_PAGE_IDS_RAW in backend/.env, '
                         'e.g. FB_PAGE_IDS_RAW=["suratcitypolice:Surat"]')

    collector = FacebookScrapeCollector()
    driver = collector._build_driver()
    try:
        route = collector._authenticate(driver)
        print(f"session ok — authenticated via {route}\n")
        page, city = settings.FB_PAGE_IDS[0]
        posts = collector._scrape_page(driver, page, city)
        print(f"{page}: {len(posts)} posts")
        for post in posts[:5]:
            when = post.created_at.isoformat(" ", "minutes") if post.created_at else "?"
            print(f"\n  @{post.author_handle} ({post.author_followers} followers) {when}"
                  f"\n  {post.text[:160]!r}"
                  f"\n  tags={post.hashtags} media={len(post.media_urls)}"
                  f" engagement={post.engagement}"
                  f"\n  {post.url}")
        if not posts:
            print("\nNo posts parsed. Re-run with FB_SCRAPE_HEADLESS=false to "
                  "watch the page — the usual causes are a login wall, a page "
                  "that is not public, or a non-English Facebook UI.")
    finally:
        driver.quit()


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        login()
