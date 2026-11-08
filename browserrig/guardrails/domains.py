import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from harnessed import Instructions, Plugin, SystemPrompt, ToolResult, hook
from harnessed.hooks import ExecuteTool, Next, Priority

from browserrig.browser import DomainNotAllowed, NavigationPolicy
from browserrig.core import ActionKind, BrowserToolMetadata


class AllowedDomains(
    Plugin, slot="browserrig.navigation-policy", provides=NavigationPolicy
):
    """Allow HTTP(S) documents only on explicit hosts or `*.host` subdomains.

    A bare host matches either HTTP or HTTPS on any port. Wildcards match strict
    subdomains only; list the apex separately. An empty list denies every web site.
    `about:blank` remains available for browser housekeeping. This is a navigation
    guard, not a network firewall: scripts, images and API requests are unaffected.
    """

    def __init__(self, domains: str | Iterable[str]) -> None:
        super().__init__()
        entries = (domains,) if isinstance(domains, str) else tuple(domains)
        self.domains = tuple(dict.fromkeys(_pattern(entry) for entry in entries))

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(
            Instructions(
                title="Allowed domains",
                text=(
                    "Browser navigation is restricted to these domains: "
                    + (", ".join(self.domains) or "none")
                    + ". A *. prefix permits strict subdomains only. Other document "
                    "destinations, including redirects, are blocked. about:blank is allowed. "
                    "JavaScript execution tools are unavailable while this guard is configured."
                ),
            )
        )

    def check(self, url: str) -> None:
        if url == "about:blank":
            return
        try:
            parts = urlsplit(url)
            host = _host(parts.hostname or "")
            # Reject malformed ports as well as credentials and browser URL ambiguities.
            _ = parts.port
            valid = (
                parts.scheme in {"http", "https"}
                and parts.username is None
                and parts.password is None
                and not any(ord(char) <= 32 or char == "\\" for char in url)
            )
        except (ValueError, UnicodeError):
            valid, host = False, ""
        if valid and any(
            host.endswith("." + pattern[2:])
            if pattern.startswith("*.")
            else host == pattern
            for pattern in self.domains
        ):
            return
        raise DomainNotAllowed(url)

    @hook(ExecuteTool, priority=Priority.GUARD)
    async def _guard_tool(
        self, event: ExecuteTool, next_: Next[ToolResult]
    ) -> ToolResult:
        metadata = (
            event.tool.metadata.get(BrowserToolMetadata)
            if event.tool is not None
            else None
        )
        if event.call.name == "execute_javascript" or (
            metadata is not None and metadata.kind == ActionKind.JAVASCRIPT
        ):
            return ToolResult.error(
                "JavaScript execution is unavailable while allowed domains are configured."
            )
        return await next_()


def _pattern(entry: str) -> str:
    if not isinstance(entry, str):
        raise TypeError("Allowed domains must be host names")
    text = entry.strip()
    wildcard = text.startswith("*.")
    try:
        host = _host(text[2:] if wildcard else text)
        if wildcard:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("IP addresses cannot have subdomains")
        return "*." + host if wildcard else host
    except (ValueError, UnicodeError) as error:
        raise ValueError(
            f"Invalid allowed domain {entry!r}; use a host such as example.com "
            "or *.example.com, without a scheme, port or path"
        ) from error


def _host(value: str) -> str:
    host = value.removesuffix(".").lower()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    host = host.encode("idna").decode("ascii")
    if len(host) > 253 or not host:
        raise ValueError("Invalid host length")
    for label in host.split("."):
        if (
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(
                char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in label
            )
        ):
            raise ValueError("Invalid host label")
    return host
