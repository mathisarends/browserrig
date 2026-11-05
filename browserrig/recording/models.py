from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecordingResult:
    """The edited video and the original captures retained beside it."""

    path: Path
    sources: tuple[Path, ...]
    original_duration: float
    duration: float


@dataclass(frozen=True, slots=True)
class Segment:
    path: Path
    target_id: str
    started_at: float
    ended_at: float


@dataclass(frozen=True, slots=True)
class Span:
    start: float
    end: float
