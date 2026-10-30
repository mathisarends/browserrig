from typing import Literal

from pydantic import Field

from browserrig.core.kinds import ObservationKind

from .options import Options


class DomMode(Options):
    kind: Literal[ObservationKind.DOM] = ObservationKind.DOM
    max_elements: int | None = Field(default=None, ge=1, le=50000)
    max_text_chars: int = Field(default=0, ge=0, le=100000)
    screenshots: bool = False
    marks: bool = True
