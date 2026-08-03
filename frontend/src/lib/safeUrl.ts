/** URL sanitisation for links that come from crawled content.
 *
 *  Post URLs, RSS item links and OSINT lookup results are all attacker-authored
 *  by definition — they come from the accounts under investigation. React
 *  escapes text, but it does NOT sanitise the href attribute: `javascript:`
 *  and `data:text/html` URLs render as clickable links and execute in the
 *  analyst's session when clicked.
 *
 *  Everything from the backend that lands in an href must pass through
 *  safeHref() first.
 */

const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

/**
 * Returns the URL if it is safe to place in an href, otherwise undefined.
 * Passing undefined to href simply renders a link with no target.
 */
export function safeHref(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined;
  const trimmed = String(raw).trim();
  if (!trimmed) return undefined;

  // Browsers strip control characters and whitespace before matching the
  // protocol, so "java\0script:" and "java\nscript:" both reach the JS handler
  // while a naive startsWith("javascript:") check sees neither. Strip them
  // before parsing, or this function inspects a different string than the
  // browser will act on.
  // eslint-disable-next-line no-control-regex
  const cleaned = trimmed.replace(/[\u0000-\u0020\u007f]/g, "");

  // Protocol-relative ("//host/path") and root-relative ("/path") URLs cannot
  // carry a scheme, so they are safe and resolve against the current origin.
  if (cleaned.startsWith("//") || cleaned.startsWith("/")) return cleaned;

  let parsed: URL;
  try {
    parsed = new URL(cleaned, window.location.origin);
  } catch {
    return undefined;
  }
  if (!SAFE_PROTOCOLS.has(parsed.protocol)) return undefined;
  return parsed.href;
}

/** True when the URL is safe to render as a link at all. */
export function isSafeUrl(raw: string | null | undefined): boolean {
  return safeHref(raw) !== undefined;
}

/**
 * Constrain a post-sign-in redirect to a path inside this app.
 *
 * "/app/feed"            -> "/app/feed"
 * "//evil.example"       -> fallback   (protocol-relative: leaves the site)
 * "/\\evil.example"      -> fallback   (browsers normalise \ to / — the
 *                                       CVE-2025-68470 bypass shape)
 * "https://evil.example" -> fallback   (absolute)
 *
 * Open redirects matter here because the sign-in page is exactly where a
 * phishing chain wants to land someone: authenticate for real, then get
 * bounced to a look-alike that asks for the password "again".
 */
export function safeInternalPath(raw: unknown, fallback = "/app"): string {
  if (typeof raw !== "string" || !raw) return fallback;
  // eslint-disable-next-line no-control-regex
  const cleaned = raw.replace(/[\u0000-\u0020\u007f]/g, "").replace(/\\/g, "/");
  if (!cleaned.startsWith("/")) return fallback;
  if (cleaned.startsWith("//")) return fallback;
  return cleaned;
}
