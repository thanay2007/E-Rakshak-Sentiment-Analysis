# -*- coding: utf-8 -*-
"""One-time browser warm-up for the automatic reverse-image search.

    python -m app.osint.lens_login

Opens a VISIBLE Chrome on the profile the Lens searches run in
(`LENS_PROFILE_DIR`) and parks it on Google Images. Browse for a moment, clear
any consent banner, solve a "verify you're human" check if one appears, and
optionally sign in to a Google account. Close the window when you are done.

Why this exists: Google decides whether to serve results or an interrogation
page partly from the browser's history, and a profile that has never been used
for anything looks exactly like a scraper. The searches themselves run headless
and need no attention — this is the one step that has to happen with a human at
the keyboard, and it is the same arrangement `app.crawlers.facebook_login` uses
for the Facebook collector, for the same reason.

Run it again whenever searches start coming back with "Google served an
anti-automation check": that means the profile's standing has lapsed, usually
after a burst of searches from one network.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from app.config import settings


def main() -> int:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception:
        print("Selenium is not installed. Run:  pip install selenium")
        return 1

    profile = Path(settings.LENS_PROFILE_DIR)
    profile.mkdir(parents=True, exist_ok=True)

    opts = Options()          # visible on purpose — that is the whole point
    opts.add_argument(f"--user-data-dir={profile}")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--lang=en-US")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    print(f"Opening Chrome on {profile}")
    print("  · clear any cookie/consent banner")
    print("  · if Google shows a 'verify you're human' check, solve it")
    print("  · try one image search by hand so the profile has done it once")
    print("  · then close the window (or press Ctrl+C here)\n")

    driver = webdriver.Chrome(options=opts)
    try:
        driver.get("https://www.google.com/imghp?hl=en")
        while True:                       # hold until the operator closes it
            time.sleep(1.5)
            try:
                if not driver.window_handles:
                    break
            except Exception:
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    (profile / ".sentinel-warm").write_text("warmed", encoding="utf-8")
    print(f"\nProfile saved. Reverse-image searches will now reuse it headlessly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
