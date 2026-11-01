from dataclasses import dataclass, field

from browserrig.core import ActionId, DocumentId, TargetId
from browserrig.events import ActionFinishedEvent, NudgeQueuedEvent


@dataclass
class TabState:
    pending: ActionFinishedEvent | None = None
    starts: dict[ActionId, float] = field(default_factory=dict)


@dataclass
class NudgeState:
    # Keyed by the caller's nudge key; a new nudge with that key replaces the old one.
    queued: dict[str, NudgeQueuedEvent] = field(default_factory=dict)
    tabs: dict[TargetId, TabState] = field(default_factory=dict)
    effect_at: float = 0
    # Documents already flagged as bot checks; each is flagged once.
    challenges: set[DocumentId] = field(default_factory=set)
    # Whether the last recorded hint observation listed any hints.
    shown: bool = False
    human_control: int = 0
