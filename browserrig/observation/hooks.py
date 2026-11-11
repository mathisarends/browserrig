from dataclasses import dataclass

from harnessed.kernel import Waterfall
from harnessed.models import UserMessage

from .models import Snapshot


@dataclass(frozen=True)
class ProjectObservation(Waterfall[UserMessage | None]):
    """Assemble one context message from the same immutable, redacted capture."""

    snapshot: Snapshot
