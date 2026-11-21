from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ScreencastFrame:
    """A base64-encoded viewport image with its tab and Chrome's Unix timestamp."""

    target_id: str
    data: str = field(repr=False)
    mime_type: str
    timestamp_seconds: float | None
