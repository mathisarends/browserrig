from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from inspect import isawaitable
from urllib.parse import urlsplit

from browserrig.core.errors import SecretError

NAME = re.compile(r"[A-Za-z0-9_.-]+")
PLACEHOLDER = re.compile(r"\{\{secret:([A-Za-z0-9_.-]+)\}\}")
# Shorter values would redact unrelated page text and leak through partial matches.
MIN_LENGTH = 4

type SecretValue = str | Callable[[], str | Awaitable[str]]

_DEFAULT_PORTS = {"http": 80, "https": 443}


def placeholder(name: str) -> str:
    return f"{{{{secret:{name}}}}}"


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
    def parse(cls, pattern: str) -> OriginPattern:
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


@dataclass(frozen=True, slots=True, eq=False)
class Secret:
    """A credential the agent types as `{{secret:NAME}}` but never sees.

    `value` is the text, or a callable returning it; callables run once when the session
    starts, except rotating ones such as `totp`, which run for each use.
    `domains` lists where it may be typed, e.g. `("github.com",)`.
    """

    value: SecretValue = field(repr=False)
    domains: tuple[str, ...] = field(kw_only=True)
    origins: tuple[OriginPattern, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        domains = (
            (self.domains,) if isinstance(self.domains, str) else tuple(self.domains)
        )
        if not domains:
            raise ValueError("A secret needs at least one domain")
        if not isinstance(self.value, str) and not callable(self.value):
            raise TypeError("A secret value must be text or a callable returning text")
        object.__setattr__(self, "domains", domains)
        object.__setattr__(
            self, "origins", tuple(OriginPattern.parse(d) for d in domains)
        )

    @property
    def rotating(self) -> bool:
        return bool(getattr(self.value, "rotating", False))

    def allows(self, origin: str) -> bool:
        return any(pattern.allows(origin) for pattern in self.origins)


async def resolve(name: str, value: SecretValue) -> str:
    """Return the text of a secret value; errors name the secret, never a value."""
    if isinstance(value, str):
        resolved: object = value
    else:
        try:
            resolved = value()
            if isawaitable(resolved):
                resolved = await resolved
        except SecretError:
            raise
        except Exception:  # pylint: disable=broad-exception-caught
            raise SecretError(f"Secret {name} could not be loaded") from None
    if not isinstance(resolved, str):
        raise SecretError(f"Secret {name} did not resolve to text")
    if len(resolved) < MIN_LENGTH:
        raise SecretError(
            f"Secret {name} is shorter than {MIN_LENGTH} characters and cannot be hidden reliably"
        )
    return resolved


def env(name: str) -> Callable[[], str]:
    """Read a secret from an environment variable when the session starts."""

    def read() -> str:
        value = os.environ.get(name)
        if not value:
            raise SecretError(f"Environment variable {name} is not set")
        return value

    read.__qualname__ = read.__name__ = f"env({name})"
    return read


class Totp:
    """RFC 6238 one-time codes; each use types the code that is valid at that moment."""

    rotating = True
    __slots__ = ("_seed", "_digits", "_period", "_digest")

    def __init__(
        self,
        seed: str | Callable[[], str],
        *,
        digits: int = 6,
        period: int = 30,
        digest: str = "sha1",
    ) -> None:
        if (
            not 6 <= digits <= 10
            or period <= 0
            or digest not in {"sha1", "sha256", "sha512"}
        ):
            raise ValueError("Invalid TOTP settings")
        if isinstance(seed, str):
            _key(seed)
        self._seed = seed
        self._digits = digits
        self._period = period
        self._digest = digest

    def __repr__(self) -> str:
        return f"Totp(digits={self._digits}, period={self._period})"

    def __call__(self) -> str:
        return self.at(time.time())

    def at(self, timestamp: float) -> str:
        seed = self._seed if isinstance(self._seed, str) else self._seed()
        counter = struct.pack(">Q", int(timestamp // self._period))
        mac = hmac.new(_key(seed), counter, getattr(hashlib, self._digest)).digest()
        offset = mac[-1] & 0x0F
        code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
        return f"{code % 10**self._digits:0{self._digits}d}"


def totp(
    seed: str | Callable[[], str],
    *,
    digits: int = 6,
    period: int = 30,
    digest: str = "sha1",
) -> Totp:
    """A one-time code generator for a base32 seed, e.g. `totp(env("GITHUB_TOTP_SEED"))`."""
    return Totp(seed, digits=digits, period=period, digest=digest)


def _key(seed: str) -> bytes:
    normalized = re.sub(r"[\s-]", "", seed).upper()
    try:
        return base64.b32decode(normalized + "=" * (-len(normalized) % 8))
    except (binascii.Error, ValueError):
        raise SecretError("TOTP seed is not valid base32") from None
