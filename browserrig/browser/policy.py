from typing import Protocol

from browserrig.core import BrowserError


class DomainNotAllowed(BrowserError):
    """A destination is outside the configured navigation policy."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Navigation blocked: domain is not allowed for {url}")


class NavigationPolicy(Protocol):
    """Optional session policy, installed before Chrome opens its first page."""

    def check(self, url: str) -> None:
        """Raise DomainNotAllowed when this document URL is outside the policy."""
        ...
