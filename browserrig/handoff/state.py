from dataclasses import dataclass, field

from browserrig.events import HandoffRequestedEvent
from browserrig.nudges import Nudges
from browserrig.observation import Snapshot


@dataclass
class Transfer:
    """One handoff to the human, from request to resume."""

    request: HandoffRequestedEvent
    before: Snapshot | None
    nudges: Nudges | None
    events: dict[str, int] = field(default_factory=dict)


@dataclass
class HandoffState:
    current: Transfer | None = None
    resume_pending: bool = False
