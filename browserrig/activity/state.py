from dataclasses import dataclass, field
from uuid import uuid4

from browserrig.events import ActivityFinishedEvent, ActivityStartedEvent

from .models import ActivityKey


@dataclass
class ActivityState:
    open: dict[ActivityKey, ActivityStartedEvent] = field(default_factory=dict)
    # The session log only holds the open turn, so intervals keep their own record.
    records: list[ActivityStartedEvent | ActivityFinishedEvent] = field(
        default_factory=list
    )
    epoch: str = field(default_factory=lambda: uuid4().hex)
