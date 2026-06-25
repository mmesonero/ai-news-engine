"""Outbound-fetch SSRF guard + URL neutralizer for rendered href/src.

Every URL the engine fetches during ingestion originates from an RSS feed entry
or a scraped page — i.e. it is attacker-influenceable. Without validation the
fetchers would happily request internal addresses (loopback, link-local cloud
metadata at 169.254.169.254, RFC-1918 ranges) and follow redirects into them.

- `is_public_url(url)` / `safe_get(client, url)`  — block SSRF on the fetch side.
- `safe_href(url)`                                 — block dangerous URL schemes
  (javascript:, data:, vbscript:, file:) on the render side; html-escaping alone
  does NOT neutralize these in an href/src attribute.

Note: validation resolves DNS up-front, so a determined DNS-rebinding attacker
could still theoretically race the resolution. Pinning the resolved IP through to
the socket would close that gap but needs a custom transport; for feed-controlled
URLs on ephemeral CI runners this up-front check is the pragmatic mitigation.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app.logging_config import get_logger

log = get_logger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 5
# Reject responses that DECLARE a body larger than this (cheap OOM guard). A
# chunked response with no Content-Length isn't caught here — callers should still
# slice the text they keep; full streaming protection would need client.stream.
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024


class UnsafeUrlError(ValueError):
    """Raised when a URL is not a public http(s) target (SSRF guard tripped)."""


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_public_url(url: str) -> bool:
    """True only if `url` is an http(s) URL whose host resolves *entirely* to
    public IP addresses. Any non-http(s) scheme, missing host, DNS failure, or a
    single private/loopback/link-local/reserved/multicast address → False
    (fail closed). All resolved addresses are checked to cover round-robin and
    dual-stack (A + AAAA) records."""
    try:
        parts = urlparse(url)
        if parts.scheme.lower() not in _ALLOWED_SCHEMES:
            return False
        host = parts.hostname
        if not host:
            return False
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return False
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(_ip_is_public(a) for a in addrs)


async def safe_get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """Like `client.get`, but validates the target (and every redirect hop) is a
    public http(s) address. Raises `UnsafeUrlError` on a blocked target. Redirects
    are followed manually (up to `_MAX_REDIRECTS`) so each `Location` is
    re-validated — any `follow_redirects` passed in kwargs is ignored on purpose.
    """
    kwargs.pop("follow_redirects", None)
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not is_public_url(current):
            raise UnsafeUrlError(current)
        resp = await client.get(current, follow_redirects=False, **kwargs)
        location = resp.headers.get("location")
        if resp.is_redirect and location:
            current = urljoin(current, location)
            continue
        declared = resp.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > _MAX_RESPONSE_BYTES:
            raise UnsafeUrlError(f"response too large ({declared} bytes): {current}")
        return resp
    raise UnsafeUrlError(f"too many redirects from {url}")


def safe_href(url: str | None) -> str:
    """Neutralize a URL for use inside an HTML href/src attribute.

    Returns the URL unchanged if it is an absolute http(s) URL or an engine-relative
    path (no scheme, e.g. `n/<slug>.html`, `../index.html`); otherwise returns `#`.
    Blocks `javascript:`/`data:`/`vbscript:`/`file:` and protocol-relative `//host`
    links that `html.escape` does not stop. Whitespace-obfuscated schemes
    (`java\\tscript:`) are caught because any colon in the first path segment of a
    scheme-less value fails the relative-path check.
    """
    if not url:
        return "#"
    u = url.strip()
    low = u.lower()
    if low.startswith(("http://", "https://")):
        return u
    if low.startswith(("javascript:", "data:", "vbscript:", "file:", "//")):
        return "#"
    # Scheme-less value: only treat as a safe relative path if its first segment
    # carries no scheme colon (rejects `mailto:`, `java\tscript:`, etc.).
    if ":" in low.split("/", 1)[0]:
        return "#"
    return u
