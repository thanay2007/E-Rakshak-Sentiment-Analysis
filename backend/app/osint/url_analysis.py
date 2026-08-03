# -*- coding: utf-8 -*-
"""Link & URL safety analysis.

Two layers:
  1. Static heuristics on the URL string — the classic phishing / obfuscation
     signals (URL shorteners, IP-literal hosts, punycode homographs, credential
     '@' tricks, deep subdomains, brand look-alikes, risky TLDs, tracking junk).
  2. Live redirect unwrapping — follow the hop chain to the final landing page
     so a shortened / cloaked link is resolved to where it actually goes.

Live resolution degrades gracefully: if the network is unavailable the static
verdict still stands and the chain is reported as unresolved.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from urllib.parse import urlparse, parse_qs

from app.security import ssrf

_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
    "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy", "t.ly", "bl.ink",
    "tiny.cc", "x.co", "soo.gd", "clck.ru", "v.gd", "trib.al", "wa.me",
}
_RISKY_TLDS = {
    "zip", "mov", "xyz", "top", "gq", "tk", "ml", "cf", "ga", "work", "click",
    "link", "country", "kim", "science", "party", "review", "loan", "date",
}
_BRANDS = ["facebook", "instagram", "whatsapp", "paytm", "sbi", "hdfc", "icici",
           "gov", "gujarat", "aadhaar", "irctc", "amazon", "google", "apple",
           "netflix", "microsoft", "phonepe", "gpay"]
_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "fbclid", "gclid",
             "utm_term", "utm_content", "mc_eid", "igshid"}
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _registered_domain(host: str) -> str:
    """Best-effort eTLD+1 without a public-suffix list — good enough for display."""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level = {"co", "com", "net", "org", "gov", "edu", "ac", "gob"}
    if parts[-2] in two_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _static_findings(url: str) -> tuple[list[dict], dict]:
    findings: list[dict] = []
    p = urlparse(url if "://" in url else "http://" + url)
    host = (p.hostname or "").lower()
    reg = _registered_domain(host)
    subs = host[: -len(reg)].strip(".") if host.endswith(reg) else ""

    def add(level, text):
        findings.append({"level": level, "text": text})

    if p.scheme != "https":
        add("medium", "Connection is not HTTPS — traffic can be intercepted or altered.")
    if "@" in (p.netloc or ""):
        add("high", "URL contains '@' — the real host is what follows it; text before "
                    "'@' is a decoy (classic credential-phishing trick).")
    if _IP_RE.match(host):
        add("high", "Host is a raw IP address, not a domain name — typical of throwaway "
                    "phishing / malware hosts.")
    if "xn--" in host:
        add("high", "Punycode domain (xn--) — may be a homograph look-alike of a real "
                    "brand using non-Latin characters.")
    if reg in _SHORTENERS:
        add("medium", f"URL shortener ({reg}) — true destination is hidden until resolved.")
    tld = reg.rsplit(".", 1)[-1]
    if tld in _RISKY_TLDS:
        add("medium", f"Top-level domain '.{tld}' is disproportionately abused for scams.")
    if subs.count(".") >= 2:
        add("medium", f"Deep subdomain nesting ({subs}.) — often used to make a hostile "
                      f"host look like a trusted brand.")
    for brand in _BRANDS:
        if brand in subs or (brand in reg and not reg.startswith(brand)):
            add("high", f"Brand name '{brand}' appears outside the registered domain "
                        f"({reg}) — likely impersonation.")
            break
    if host.count("-") >= 3:
        add("low", "Many hyphens in the host — common in generated/typosquat domains.")
    if p.port and p.port not in (80, 443):
        add("low", f"Non-standard port :{p.port}.")
    if reg and _entropy(reg.split(".")[0]) >= 3.6:
        add("low", "High-randomness domain string — may be auto-generated.")
    for ext in (".apk", ".exe", ".scr", ".zip", ".rar"):
        if p.path.lower().endswith(ext):
            add("high", f"Link points directly to a downloadable file ({ext}).")
            break
    q = parse_qs(p.query)
    tracking = [k for k in q if k in _TRACKING]
    if tracking:
        add("info", f"Tracking parameters present: {', '.join(tracking)}.")

    if not findings:
        add("ok", "No static phishing or obfuscation signals in the URL string.")

    meta = {"scheme": p.scheme or "http", "host": host,
            "registered_domain": reg, "path": p.path or "/",
            "is_shortener": reg in _SHORTENERS}
    return findings, meta


async def _resolve_chain(url: str, *, max_hops: int = 8, timeout: float = 6.0) -> dict:
    """Unwrap the redirect chain through the SSRF guard.

    Every hop is revalidated against the blocked-range table (security/ssrf.py),
    so a shortener that points at 169.254.169.254 or an internal admin panel is
    refused rather than fetched. A refusal is surfaced to the analyst as a
    finding — a link that tries to make the server hit its own network is
    itself a strong signal about the link.
    """
    try:
        chain, _final = await ssrf.safe_chain(
            url, max_hops=max_hops, timeout=timeout,
            headers={"User-Agent": _UA},
            # Only headers and status codes matter here; the body is never shown.
            max_bytes=64 * 1024)
        return {"resolved": True, "hops": len(chain), "chain": chain,
                "final_url": chain[-1]["url"] if chain else url}
    except ssrf.BlockedRequest as exc:
        return {"resolved": False, "blocked": True, "reason": str(exc),
                "hops": 0, "chain": [], "final_url": None}
    except Exception as exc:
        # Type name only — never the exception text, which can echo internal
        # hostnames and addresses back to the caller.
        return {"resolved": False, "reason": f"Could not reach host ({type(exc).__name__}).",
                "hops": 0, "chain": [], "final_url": None}


_LEVEL_WEIGHT = {"high": 34, "medium": 18, "low": 7, "info": 1, "ok": 0}


def _risk(findings: list[dict], chain: dict) -> tuple[int, str]:
    score = sum(_LEVEL_WEIGHT.get(f["level"], 0) for f in findings)
    if chain.get("resolved") and chain.get("hops", 1) >= 4:
        score += 10   # long redirect chains hide the destination
    score = min(score, 100)
    level = "dangerous" if score >= 60 else "suspicious" if score >= 30 else \
        "caution" if score >= 12 else "clean"
    return score, level


async def analyze_url(url: str, *, resolve: bool = True) -> dict:
    url = (url or "").strip()
    if not url or " " in url or "." not in url:
        return {"url": url, "valid": False, "error": "Not a valid URL."}

    findings, meta = _static_findings(url)
    chain = await _resolve_chain(url) if resolve else {"resolved": False,
                                                       "reason": "resolution disabled",
                                                       "chain": [], "final_url": None}

    # Re-run static checks on the resolved destination so a shortener's real
    # target is judged, not just the short link.
    dest_findings = []
    final = chain.get("final_url")
    if final and final != url:
        dest_findings, dest_meta = _static_findings(final)
        meta["final_registered_domain"] = dest_meta["registered_domain"]

    all_findings = findings + [{**f, "on": "destination"} for f in dest_findings
                               if f["level"] != "ok"]
    if chain.get("blocked"):
        all_findings.append({
            "level": "high",
            "text": "This link points into a private or internal network rather "
                    "than the public internet. Resolution was refused. Links "
                    "like this are used to make a server attack its own network.",
        })
    score, level = _risk(all_findings, chain)
    return {
        "url": url, "valid": True, "risk_score": score, "risk_level": level,
        "meta": meta, "redirect": chain, "findings": all_findings,
    }
