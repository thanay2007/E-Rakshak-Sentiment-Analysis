"""One-time interactive Instagram login — writes backend/ig_session.json.

    cd backend && python -m app.crawlers.instagrapi_login          # log in
    cd backend && python -m app.crawlers.instagrapi_login --verify # prove it works

Instagram answers a fresh password login from an unfamiliar IP with a
checkpoint: a code sent to the account's email or phone, sometimes a 2FA code
on top. Answering it needs a console. The ingestion loop has none — it would
just see the login raise and log a failure every cycle — so the handshake
happens here once, and the collector reuses the saved device+session dump
afterwards.

The dump is written to a file and never printed: it is full account access with
no further prompt, exactly like the Telegram session string. It is in
.gitignore; treat a copy of it as a live credential.

--verify does a small live read (profile, one seed page, one watchlist hashtag,
one comment thread) so a deployment can be confirmed end to end without waiting
for a crawl tick. It is deliberately a handful of calls: the private API is
rate-limited per account, and a "test" that pulls hundreds of media is how the
burner gets challenged again.

Use a dedicated account, never a personal one — private-API traffic can get an
account rate-limited or banned.
"""
import sys

from app.config import settings
from app.crawlers.instagrapi_ig import SESSION_FILE

# A Windows console defaults to cp1252, which cannot encode a single Gujarati
# or Devanagari character — so printing a real Surat caption killed this tool
# with a UnicodeEncodeError on exactly the content it exists to prove works.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def _ask_code(username: str, choice) -> str:
    """instagrapi's challenge_code_handler: return the code, or "" to give up."""
    where = getattr(choice, "name", str(choice)).lower()
    print(f"\nInstagram sent a verification code to @{username}'s {where}.")
    return input("Code (blank to abort): ").strip()


def _build_client():
    from instagrapi import Client

    client = Client()
    client.delay_range = [2, 5]
    client.challenge_code_handler = _ask_code
    if SESSION_FILE.exists():
        try:
            client.load_settings(SESSION_FILE)
            print(f"Loaded existing {SESSION_FILE.name} — reusing its device id.")
        except Exception as exc:
            print(f"Ignoring unreadable {SESSION_FILE.name}: {exc}")
    return client


def login() -> None:
    if not (settings.IG_USERNAME and settings.IG_PASSWORD) and not settings.IG_SESSIONID:
        raise SystemExit(
            "Set IG_USERNAME and IG_PASSWORD (or IG_SESSIONID) in backend/.env first.")

    client = _build_client()
    if settings.IG_SESSIONID:
        print("Using IG_SESSIONID (no fresh login — the cheapest route).")
        client.login_by_sessionid(settings.IG_SESSIONID)
    else:
        print(f"Logging in as @{settings.IG_USERNAME} ...")
        # A 2FA account rejects the login and asks for a TOTP code; the
        # challenge handler above covers the email/SMS checkpoint instead.
        try:
            client.login(settings.IG_USERNAME, settings.IG_PASSWORD)
        except Exception as exc:
            if "two_factor" not in str(exc).lower() and "2fa" not in str(exc).lower():
                raise
            code = input("Two-factor code from your authenticator app: ").strip()
            client.login(settings.IG_USERNAME, settings.IG_PASSWORD,
                         verification_code=code)

    client.dump_settings(SESSION_FILE)
    me = client.account_info()
    print(f"\nLogged in as @{me.username} ({me.full_name}) — "
          f"{me.follower_count} followers.")
    print(f"Session written to {SESSION_FILE}. It was not printed: it is full "
          "account access. Revoke it any time from Instagram > Settings > "
          "Security > Login activity, then re-run this.")
    print("\nThe 'Instagram (instagrapi)' collector will pick it up on the next "
          "API start — no further configuration needed.")


def verify() -> None:
    """A small live read across all four legs: users, posts, hashtags, comments."""
    if not SESSION_FILE.exists() and not settings.IG_SESSIONID:
        raise SystemExit("No session yet — run without --verify first.")

    from app.crawlers.instagrapi_ig import InstagrapiCollector

    collector = InstagrapiCollector()
    client = collector._login_sync()
    me = client.account_info()
    print(f"session ok — signed in as @{me.username}\n")

    # users + posts: the first seed page, through the adapter's own path.
    seeds = settings.IG_SEED_USERNAMES
    if seeds:
        username, city = seeds[0]
        harvest = collector._account_medias_sync(client, username, city, 3)
    else:
        username, harvest = "", []

    # hashtags: one real watchlist tag.
    from app.services.watch_targets import watch_terms
    terms = [t for t in watch_terms() if t.replace("#", "").isalnum()] or ["surat"]
    tagged = collector._enrich_authors_sync(
        client, collector._hashtags_sync(client, terms[:1]))

    # Map every media exactly once — the adapter's seen-set means a second
    # _media_to_post on the same media returns None by design.
    pool = harvest + tagged
    by_media: dict[str, object] = {}
    for m, city, profile in pool:
        if (post := collector._media_to_post(m, city, profile)):
            by_media[str(getattr(m, "pk", "") or "")] = post

    def _show(label, items):
        print(f"\n{label}: {len(items)} media")
        for m, _city, _profile in items[:3]:
            post = by_media.get(str(getattr(m, "pk", "") or ""))
            if post:
                print(f"  @{post.author_handle} ({post.author_followers} followers,"
                      f" verified={post.author_verified}) {post.text[:70]!r}"
                      f" tags={post.hashtags}")

    _show(f"users/posts @{username}" if username else "users/posts (no seeds)", harvest)
    _show(f"hashtags #{terms[0].lstrip('#')}", tagged)

    # comments: the loudest media of whatever the two legs above found.
    comments = collector._comments_sync(client, pool, by_media)
    print(f"\ncomments: {len(comments)} fetched")
    for c in comments[:5]:
        print(f"  @{c.author_handle}: {c.text[:70]!r}")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        login()
