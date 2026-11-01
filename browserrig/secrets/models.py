import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from inspect import isawaitable

from browserrig.core import SecretError

from .origin import OriginPattern
from .totp import Totp

NAME = re.compile(r"[A-Za-z0-9_.-]+")
PLACEHOLDER = re.compile(r"\{\{secret:([A-Za-z0-9_.-]+)\}\}")
# Shorter values would redact unrelated page text and leak through partial matches.
_MIN_LENGTH = 4

type SecretValue = str | Callable[[], str | Awaitable[str]]


def placeholder(name: str) -> str:
    return f"{{{{secret:{name}}}}}"


@dataclass(frozen=True, slots=True, eq=False)
class Secret:
    """A credential the agent types as `{{secret:NAME}}` but never sees.

    `value` is the text, or a callable returning it; callables run once when the session
    starts, except a `Totp`, which runs for each use.
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
        return isinstance(self.value, Totp)

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
    if len(resolved) < _MIN_LENGTH:
        raise SecretError(
            f"Secret {name} is shorter than {_MIN_LENGTH} characters and cannot be hidden reliably"
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
