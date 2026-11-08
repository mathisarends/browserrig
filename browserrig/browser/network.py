"""Which content requests a tab has in flight, for readiness to weigh against the DOM.

Only requests that can still change what the page shows are kept: documents, scripts,
stylesheets, XHR and fetch. Sockets, event streams, beacons and media never finish
by design, so they are not recorded at all.
"""

from dataclasses import dataclass
from time import monotonic

from cdpify.domains.network import (
    LoadingFailedEvent,
    LoadingFinishedEvent,
    RequestWillBeSentEvent,
    ResourceType,
)

_CONTENT = frozenset(
    {
        ResourceType.DOCUMENT,
        ResourceType.SCRIPT,
        ResourceType.STYLESHEET,
        ResourceType.XHR,
        ResourceType.FETCH,
    }
)
# Finished requests older than any readiness budget are dropped once this many pile up.
_PRUNE_AT = 256
_RETAIN_SECONDS = 120


@dataclass(frozen=True, slots=True)
class Request:
    """A content request; `finished` is None while it is in flight."""

    started: float
    finished: float | None = None


class NetworkActivity:
    """Start and end times of a tab's content requests, on the `monotonic` clock."""

    def __init__(self) -> None:
        self._requests: dict[str, Request] = {}

    def handle(self, event: object) -> None:
        now = monotonic()
        match event:
            case RequestWillBeSentEvent(request_id=rid, type=kind) if kind in _CONTENT:
                # A redirect reuses the id and continues the same request.
                if rid not in self._requests:
                    if len(self._requests) >= _PRUNE_AT:
                        self._prune(now)
                    self._requests[rid] = Request(now)
            case (
                LoadingFinishedEvent(request_id=rid)
                | LoadingFailedEvent(request_id=rid)
            ):
                if (request := self._requests.get(rid)) and request.finished is None:
                    self._requests[rid] = Request(request.started, now)

    def since(self, started: float) -> tuple[Request, ...]:
        """Requests that started at or after `started`, oldest first."""
        return tuple(
            sorted(
                (r for r in self._requests.values() if r.started >= started),
                key=lambda request: request.started,
            )
        )

    def _prune(self, now: float) -> None:
        horizon = now - _RETAIN_SECONDS
        self._requests = {
            rid: request
            for rid, request in self._requests.items()
            if (request.finished or request.started) >= horizon
        }
