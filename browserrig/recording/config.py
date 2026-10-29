from pathlib import Path

from pydantic import Field

from browserrig.core.options import Options


class RecordingOptions(Options):
    directory: Path = Path(".browserrig/recordings")
    frame_rate: int = Field(default=24, ge=1, le=60)
    max_width: int = Field(default=1920, ge=320, le=7680)
    max_height: int = Field(default=1080, ge=240, le=4320)
    max_bytes: int = Field(default=512 * 1024 * 1024, ge=1024)
    timeout: float = Field(default=30, gt=0, le=180)
    required: bool = False
    record_during_pause: bool = True
