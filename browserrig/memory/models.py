from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from harnessed.events import DurableEvent

from browserrig.core import Options


class MemoryAction(StrEnum):
    CHECKPOINT_REQUESTED = "checkpoint_requested"
    SAVED = "saved"
    COMPACTED = "compacted"
    RESTORE_REQUESTED = "restore_requested"
    RESTORED = "restored"
    PARTIAL_READ = "partial_read"
    UNAVAILABLE = "unavailable"


class TaskMemoryState(Options):
    """Metadata only; the workspace file is the canonical working memory."""

    path: str
    revision: str | None = None
    checkpoint_requested: bool = False
    checkpoint_saved: bool = False
    compaction_id: str | None = None
    restore_pending: bool = False


@dataclass(frozen=True)
class TaskMemoryEvent(DurableEvent):
    """An observable handover, not proof that the notes or task are correct."""

    action: MemoryAction
    path: str
    revision: str | None
    compaction_id: str | None
    checkpoint_saved: bool
    restore_pending: bool
    type: Literal["browserrig.memory"] = field(
        default="browserrig.memory", kw_only=True
    )
