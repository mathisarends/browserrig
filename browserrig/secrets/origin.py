from dataclasses import dataclass
from typing import Self
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True, slots=True)
class OriginPattern:
    """Where a secret may be typed: one scheme, one host or its subdomains, one or any port."""

    scheme: str
    host: str
    port: int | None = None
    subdomains: bool = False

    def __str__(self) -> str:
        host = f"*.{self.host}" if self.subdomains else self.host
        default = self.port is None or self.port == _DEFAULT_PORTS[self.scheme]
        port = "" if default else f":{self.port}"
        return f"{self.scheme}://{host}{port}"

    @classmethod
    def parse(cls, pattern: str) -> Self:
        """`github.com` is that host over https on any port, `*.github.com` its subdomains.

        A full origin such as `http://127.0.0.1:8000` fixes scheme and port.
        """
        text = pattern.strip()
        if "://" in text:
            parts = urlsplit(text)
            scheme = parts.scheme.lower()
            if scheme not in _DEFAULT_PORTS:
                raise ValueError(
                    f"Secret domain {pattern!r} needs an http or https origin"
                )
            if (
                parts.path not in ("", "/")
                or parts.query
                or parts.fragment
                or "@" in text
            ):
                raise ValueError(
                    f"Secret domain {pattern!r} must be an origin without a path"
                )
            try:
                port = parts.port or _DEFAULT_PORTS[scheme]
            except ValueError:
                raise ValueError(
                    f"Secret domain {pattern!r} has an invalid port"
                ) from None
            host = parts.hostname or ""
        else:
            if any(character in text for character in "/:?#@ \\"):
                raise ValueError(
                    f"Secret domain {pattern!r} must be a host such as github.com "
                    "or a full origin such as http://127.0.0.1:8000"
                )
            scheme, port, host = "https", None, text
        subdomains = host.startswith("*.")
        if subdomains:
            host = host[2:]
        host = _normalize_host(host)
        if not host or "*" in host or host.startswith(".") or host.endswith("."):
            raise ValueError(f"Secret domain {pattern!r} is not a valid host")
        return cls(scheme, host, port, subdomains)

    def allows(self, origin: str) -> bool:
        """Match a browser origin such as `location.origin`; opaque origins never match."""
        if origin == "null":
            return False
        parts = urlsplit(origin)
        scheme = parts.scheme.lower()
        if scheme != self.scheme or not parts.hostname:
            return False
        try:
            port = parts.port or _DEFAULT_PORTS[scheme]
        except ValueError:
            return False
        if self.port is not None and port != self.port:
            return False
        host = _normalize_host(parts.hostname)
        if self.subdomains:
            return host.endswith("." + self.host)
        return host == self.host


def _normalize_host(host: str) -> str:
    host = host.lower()
    if host.isascii():
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
