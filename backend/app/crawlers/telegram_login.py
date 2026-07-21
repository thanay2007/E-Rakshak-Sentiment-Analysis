"""One-time interactive Telegram login — writes the session string to .env.

    cd backend && python -m app.crawlers.telegram_login

Telegram authorizes a client with an SMS/app code (and 2FA password if the
account has one), which needs a console. The ingestion loop has none, so that
handshake happens here once and the resulting StringSession is written straight
into backend/.env, after which the collector logs in unattended.

The string is written to the file rather than printed on purpose: it is full
account access with no 2FA prompt, so it should never pass through a terminal
scrollback, a screenshot or a clipboard. Pass --print to override that (e.g.
when configuring a remote host), and treat the output as a live credential.

Needs TELEGRAM_API_ID / TELEGRAM_API_HASH in .env first — create an app at
https://my.telegram.org > API development tools. Use a dedicated account, not
a personal one: monitoring traffic can get an account rate-limited or banned.
"""
import asyncio
import re
import sys

from app.config import BASE_DIR, settings

ENV_PATH = BASE_DIR / ".env"
KEY = "TELEGRAM_SESSION_STRING"


def write_env(value: str) -> str:
    """Set KEY in backend/.env, replacing any existing line. Returns what
    happened, so the caller can say so without echoing the secret."""
    line = f"{KEY}={value}"
    if not ENV_PATH.exists():
        ENV_PATH.write_text(line + "\n", encoding="utf-8")
        return f"created {ENV_PATH} with {KEY}"
    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(rf"(?m)^{KEY}=", text):
        text = re.sub(rf"(?m)^{KEY}=.*$", line, text)
        action = f"replaced {KEY} in {ENV_PATH}"
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
        action = f"added {KEY} to {ENV_PATH}"
    ENV_PATH.write_text(text, encoding="utf-8")
    return action


async def main() -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if not (settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH):
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in backend/.env first.")

    async with TelegramClient(StringSession(), settings.TELEGRAM_API_ID,
                              settings.TELEGRAM_API_HASH) as client:
        me = await client.get_me()
        session = client.session.save()
        print(f"\nLogged in as {me.first_name} (@{me.username})")

        if "--print" in sys.argv:
            print(f"\n{KEY}={session}\n")
            print("That string is a live credential — full account access, no 2FA "
                  "prompt. Do not paste it into chats, issues or screenshots.")
            return

        print(write_env(session))
        print("\nDone — the collector will use MTProto on next start.")
        print("The session string was written to .env and deliberately not shown; "
              "it is full account access. Revoke it any time from "
              "Telegram > Settings > Devices, then re-run this.")


if __name__ == "__main__":
    asyncio.run(main())
