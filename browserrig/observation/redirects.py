"""Search engines wrap result links in click-tracking redirects that carry the real target."""

import base64
import binascii
import re
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

_BING = re.compile(r"(^|\.)bing\.com$")
_GOOGLE = re.compile(r"(^|\.)google\.[a-z.]+$")
_DUCKDUCKGO = re.compile(r"(^|\.)duckduckgo\.com$")
_YAHOO_TARGET = re.compile(r"/RU=([^/]+)/")


def unwrap_redirect(href: str) -> str:
    """The destination of a known search-engine redirect link, otherwise `href` unchanged."""
    parts = urlsplit(href)
    host = parts.hostname or ""
    query = parse_qs(parts.query)
    target = ""
    if _BING.search(host) and parts.path == "/ck/a":
        encoded = query.get("u", [""])[0]
        target = _base64(encoded[2:]) if encoded.startswith("a1") else ""
    elif _GOOGLE.search(host) and parts.path == "/url":
        target = (query.get("q") or query.get("url") or [""])[0]
    elif _DUCKDUCKGO.search(host) and parts.path.startswith("/l/"):
        target = query.get("uddg", [""])[0]
    elif host == "r.search.yahoo.com" and (match := _YAHOO_TARGET.search(parts.path)):
        target = unquote(match.group(1))
    if not target:
        return href
    # Bing also wraps its own tabs, whose targets are paths on the search site.
    resolved = urljoin(href, target)
    return resolved if urlsplit(resolved).scheme in ("http", "https") else href


def _base64(value: str) -> str:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
