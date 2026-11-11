from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from harnessed.kernel import Waterfall

from .kinds import TabGesture


@dataclass(frozen=True)
class ChangeTab(Waterfall[None]):
    """A requested tab operation; hooks may wrap the backend operation."""

    gesture: TabGesture
    target_id: str


type TabDispatch = Callable[[ChangeTab, Callable[[], Awaitable[None]]], Awaitable[None]]
