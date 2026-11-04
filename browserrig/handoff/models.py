from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import Field

from browserrig.core import HandoffStatus, Options
from browserrig.events import HandoffRequestedEvent


class HumanResponse(Options):
    """A human's report; completion still needs verification against the page."""

    status: Literal[HandoffStatus.DONE, HandoffStatus.DECLINED] = HandoffStatus.DONE
    note: str = Field(default="", max_length=2000)


class HandoffReceipt(Options):
    """Immutable handoff record shared by tool results and HumanHandoff.history."""

    handoff_id: str
    source: Literal["tool", "pause"]
    status: HandoffStatus
    reason: str
    expected_state: str = ""
    human_note: str = ""
    changes: tuple[str, ...] = ()
    current_url: str | None = None
    next: str = "Inspect the fresh browser observation; completion is not verified."


type HandoffCallback = Callable[[HandoffRequestedEvent], Awaitable[HumanResponse]]
