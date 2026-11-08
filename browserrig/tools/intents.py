"""What tools are about to do, as hooks that other plugins can stage for viewers.

Tools only describe their steps. Nothing here emits events or pauses; without a plugin
hooked in, every step simply runs.
"""

from dataclasses import dataclass
from typing import Any

from harnessed.kernel import Event, Waterfall

from browserrig.browser import Tab
from browserrig.core import Bounds, Point


@dataclass(frozen=True, slots=True)
class FindIntent:
    """Search the page for `queries`, then show match number `match`.

    The step returns the final `PageMatches`. Searches sharing `session` reuse the page
    text; the tool closes the session afterwards.
    """

    queries: tuple[str, ...]
    match: int
    session: str


@dataclass(frozen=True, slots=True)
class NavigateIntent:
    """Load `url`, which a person would enter in the address bar as `typed`."""

    url: str
    typed: str


@dataclass(frozen=True, slots=True)
class OpenFileIntent:
    """Open a local file in a new tab."""

    path: str


@dataclass(frozen=True, slots=True)
class UploadIntent:
    """Assign `paths` to a file input, optionally showing its visible target at `point`."""

    paths: tuple[str, ...]
    point: Point | None = None


@dataclass(frozen=True, slots=True)
class WaitIntent:
    """Let the page work for `seconds`; the step does the waiting."""

    seconds: float


type Intent = FindIntent | NavigateIntent | OpenFileIntent | UploadIntent | WaitIntent


@dataclass(frozen=True)
class Perform(Waterfall[Any]):
    """Run one step of a tool in `tab`; hooks may stage it around `next_`.

    The terminal handler is the step itself, and its result passes back unchanged.
    `action_id` names the action the step belongs to, or is empty outside one.
    """

    intent: Intent
    tab: Tab
    action_id: str


@dataclass(frozen=True)
class TargetLocated(Event[None]):
    """The next input in `tab` aims at element `ref`, which covers `bounds`."""

    tab: Tab
    ref: str
    bounds: Bounds
    action_id: str
