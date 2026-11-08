from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecordingResult:
    """The edited video, its uncut counterpart and the native captures beside them."""

    path: Path
    original_path: Path
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
