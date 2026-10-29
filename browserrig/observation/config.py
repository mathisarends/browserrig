from typing import Annotated, Literal

from pydantic import Field

from browserrig.browser.config import Options
from browserrig.kinds import ObservationKind


class WebMode(Options):
    kind: Literal[ObservationKind.WEB] = ObservationKind.WEB
    max_elements: int = Field(default=150, ge=1, le=1000)
    max_text_chars: int = Field(default=12000, ge=0, le=100000)
    screenshots: bool = False


class FigmaMode(Options):
    kind: Literal[ObservationKind.FIGMA] = ObservationKind.FIGMA
    selector: str = "canvas"
    loading_selector: str = '[role="progressbar"], [aria-busy="true"]'
    screenshots: Literal[True] = True
    min_color_fraction: float = Field(default=0.002, ge=0, le=0.2)


type ObservationMode = Annotated[WebMode | FigmaMode, Field(discriminator="kind")]
