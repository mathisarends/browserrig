from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from browserrig.browser import Tab
from browserrig.core import ElementPoint, Point, StaleElement

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


@dataclass(frozen=True, slots=True)
class RevealStep:
    """One applied DOM reveal step, measured in container-local CSS pixels."""

    frame_id: str
    container: str
    before: Point
    after: Point

    @property
    def changed(self) -> bool:
        return self.before != self.after


@runtime_checkable
class ScrollableElement(Protocol):
    """Optional wheel planning; input remains with Mouse and its Motor."""

    async def scroll_step(self) -> ScrollStep | None: ...


class EmptyReferences:
    """A backend that has not published targets grants no reference capabilities."""

    async def resolve(self, tab: Tab, snapshot: Snapshot, ref: str) -> ElementHandle:
        raise StaleElement("This observation has no element references")


@runtime_checkable
class RevealableElement(Protocol):
    """Optional backend-owned preparation before the shared pointer locates a ref."""

    async def reveal(self, *, report: Callable[[str], None] | None = None) -> bool: ...
