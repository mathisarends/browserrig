from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from browserrig.browser import Tab
from browserrig.core import ElementPoint, Point

from .models import ElementInfo, Snapshot


class ElementHandle(Protocol):
    """Locate a live target in viewport CSS pixels without performing input."""

    @property
    def element(self) -> ElementInfo: ...

    async def locate(  # pylint: disable=unused-argument
        self, *, aim: tuple[float, float] | None = None
    ) -> ElementPoint: ...


class References(Protocol):
    """Resolve opaque refs from one capture; probes keep their own resolver.

    Refs must not be reassigned to another object within the same tab/document.
    Resolution and location validate the backend's current object and only read state.
    """

    async def resolve(  # pylint: disable=unused-argument
        self, tab: Tab, snapshot: Snapshot, ref: str
    ) -> ElementHandle: ...


@dataclass(frozen=True, slots=True)
class ScrollStep:
    """One wheel input in viewport CSS pixels; `key` detects a stalled plan."""

    point: Point
    delta_x: float
    delta_y: float
    key: str


@runtime_checkable
class ScrollableElement(Protocol):
    """Optional wheel planning; input remains with Mouse and its Motor."""

    async def scroll_step(self) -> ScrollStep | None: ...
