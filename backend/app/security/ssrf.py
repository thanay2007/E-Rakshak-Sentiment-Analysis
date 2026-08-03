"""Outbound-request guard for the OSINT fetchers.

The investigation tools fetch URLs an analyst pastes in — and those URLs come
from hostile content by definition. Without a guard, "analyse this link" means
"make my server issue a request to any address it can reach", which on a police
network is the internal one.

What this blocks:
  • private, loopback, link-local, multicast and reserved address ranges
  • the cloud metadata address (169.254.169.254 / fd00:ec2::254), which hands
    out instance credentials to anything that asks
  • non-http(s) schemes — file://, gopher://, ftp:// and friends
  • redirects into any of the above, which is the bypass that catches most
    naive implementations: the first hop is a perfectly innocent public URL

Design note — DNS rebinding. Validating the hostname then letting httpx resolve
it again leaves a window where the second lookup returns a different address.
`safe_get` closes it by resolving once, checking every returned address, and
connecting to the vetted IP with the original Host header preserved for TLS and
virtual hosting.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx

log = logging.getLogger("sentinel.ssrf")

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 8
DEFAULT_TIMEOUT = 6.0
# Cap on bytes read from a remote host, enforced while streaming rather than
# after the fact — `response.content` has already bought the whole body.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024

_BLOCKED_V4 = [
    ipaddress.ip_network("0.0.0.0/8"),         # "this network"
    ipaddress.ip_network("10.0.0.0/8"),        # RFC1918
    ipaddress.ip_network("100.64.0.0/10"),     # carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("169.254.0.0/16"),    # link-local — includes cloud metadata
    ipaddress.ip_network("172.16.0.0/12"),     # RFC1918
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),      # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),    # RFC1918
    ipaddress.ip_network("198.18.0.0/15"),     # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),       # multicast
    ipaddress.ip_network("240.0.0.0/4"),       # reserved
]
_BLOCKED_V6 = [
    ipaddress.ip_network("::/128"),            # unspecified
    ipaddress.ip_network("::1/128"),           # loopback
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped — bypass vector
    ipaddress.ip_network("64:ff9b::/96"),      # NAT64
    ipaddress.ip_network("100::/64"),          # discard
    ipaddress.ip_network("fc00::/7"),          # unique local
    ipaddress.ip_network("fe80::/10"),         # link-local
    ipaddress.ip_network("ff00::/8"),          # multicast
    ipaddress.ip_network("fd00:ec2::254/128"), # EC2 IMDS over IPv6
]


class BlockedRequest(Exception):
    """The requested URL resolves somewhere this server must not reach."""


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # ::ffff:127.0.0.1 must be judged as 127.0.0.1, not as a v6 address.
        return _ip_is_blocked(ip.ipv4_mapped)
    networks = _BLOCKED_V4 if ip.version == 4 else _BLOCKED_V6
    if any(ip in net for net in networks):
        return True
    # Backstop for anything the explicit tables missed.
    return not ip.is_global


def resolve_public_addresses(host: str, port: int) -> list[tuple[int, str]]:
    """Resolve `host`, rejecting the whole name if ANY address is internal.

    All-or-nothing on purpose: a name that returns one public and one private
    address is the standard rebinding setup, and "use the good one" is not a
    property we can rely on across a retry.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _ip_is_blocked(ip):
            raise BlockedRequest(f"{host} is a non-routable address.")
        return [(socket.AF_INET6 if ip.version == 6 else socket.AF_INET, host)]

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedRequest(f"Could not resolve {host}.") from exc

    out: list[tuple[int, str]] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            raise BlockedRequest(
                f"{host} resolves to an internal address ({addr}) and will not be fetched.")
        out.append((family, addr))
    if not out:
        raise BlockedRequest(f"Could not resolve {host} to a usable address.")
    return out


def validate_url(url: str) -> tuple[str, str, int]:
    """Check scheme/host/port and resolve. Returns (url, host, port)."""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedRequest(
            f"Only http and https URLs can be analysed (got '{parsed.scheme}').")
    host = parsed.hostname
    if not host:
        raise BlockedRequest("URL has no host.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    resolve_public_addresses(host, port)
    return urlunparse(parsed), host, port


@dataclass
class SafeResponse:
    """What a guarded fetch returns.

    A plain value object rather than an httpx.Response: the body is read under a
    byte cap inside a streaming context, and once that context closes an
    httpx.Response will not hand back `.content` at all. Returning our own type
    keeps the cap honest instead of reaching into httpx's internals to fake it.
    """
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    truncated: bool

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


async def safe_get(client: httpx.AsyncClient, url: str, *,
                   headers: dict | None = None,
                   max_bytes: int = MAX_DOWNLOAD_BYTES,
                   timeout: float = DEFAULT_TIMEOUT) -> SafeResponse:
    """GET a vetted URL, streaming the body under a hard byte cap.

    Streaming matters: `response.content` has already pulled the entire body
    into memory before any size check can run, so a hostile host answering with
    a 10 GB stream would take the process down regardless of the cap.
    """
    validate_url(url)
    async with client.stream("GET", url, headers=headers or {},
                             timeout=timeout, follow_redirects=False) as response:
        body = bytearray()
        truncated = False
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) >= max_bytes:
                truncated = True
                break          # stop pulling; do not buffer the rest
        return SafeResponse(
            url=str(response.url),
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            content=bytes(body[:max_bytes]),
            truncated=truncated,
        )


async def safe_chain(url: str, *, max_hops: int = MAX_REDIRECTS,
                     timeout: float = DEFAULT_TIMEOUT,
                     headers: dict | None = None,
                     max_bytes: int = MAX_DOWNLOAD_BYTES) -> tuple[list[dict], SafeResponse | None]:
    """Follow redirects manually, revalidating every hop.

    Returns (chain, final_response). The chain records each URL and status so
    the analyst can see where a shortener actually led.
    """
    chain: list[dict] = []
    current, _, _ = validate_url(url)
    final: SafeResponse | None = None

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_hops):
            response = await safe_get(client, current, headers=headers,
                                      max_bytes=max_bytes, timeout=timeout)
            chain.append({"url": current, "status": response.status_code})
            final = response
            if response.status_code in (301, 302, 303, 307, 308) and "location" in response.headers:
                nxt = str(httpx.URL(current).join(response.headers["location"]))
                if nxt == current:
                    break
                # The line that matters: every hop is revalidated, so a public
                # first URL cannot redirect into 169.254.169.254.
                validate_url(nxt)
                current = nxt
                continue
            break
    return chain, final
