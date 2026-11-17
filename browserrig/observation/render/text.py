import re
from urllib.parse import unquote, urlsplit

from browserrig.observation.redirects import unwrap_redirect

_MAX_HREF = 80


# Footnote markers such as [1], [a] or [note 3].
_FOOTNOTE = re.compile(r"\[\w[\w ]{0,7}\]")


def quote(text: str, limit: int) -> str:
    return '"' + cut(text, limit).replace('"', "'") + '"'


def format_link(href: str, url: str, name: str = "") -> str:
    """Same-page links as fragments, same-origin links as paths; script links are omitted."""
    href = unwrap_redirect(href)
    parts = urlsplit(href)
    if parts.scheme not in ("http", "https", "mailto", "tel"):
        return ""
    page = url.split("#", 1)[0]
    if href.startswith(page + "#"):
        fragment = href[len(page) + 1 :]
        # Table-of-contents entries and footnote markers say nothing more with their target.
        if (
            not fragment
            or unquote(fragment).replace("_", " ").casefold() == name.casefold()
            or _FOOTNOTE.fullmatch(name)
        ):
            return ""
        return cut("#" + fragment, _MAX_HREF)
    origin = _origin(url)
    if origin and href.startswith(origin + "/"):
        href = href[len(origin) :]
    return cut(href, _MAX_HREF)


def cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return (
        f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") else ""
    )
