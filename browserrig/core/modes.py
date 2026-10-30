from typing import Annotated, Literal

from pydantic import Field

from browserrig.core.kinds import ObservationKind

from .options import Options


class DomMode(Options):
    kind: Literal[ObservationKind.DOM] = ObservationKind.DOM
    max_elements: int | None = Field(default=None, ge=1, le=50000)
    max_text_chars: int = Field(default=0, ge=0, le=100000)
    screenshots: bool = False
    marks: bool = True


class CanvasMode(Options):
    kind: Literal[ObservationKind.CANVAS] = ObservationKind.CANVAS
    selector: str = "canvas"
    loading_selector: str = '[role="progressbar"], [aria-busy="true"]'
    screenshots: Literal[True] = True
    min_color_fraction: float = Field(default=0.002, ge=0, le=0.2)


type ObservationMode = Annotated[DomMode | CanvasMode, Field(discriminator="kind")]
