from pydantic import Field

from browserrig.browser.config import Options


class ReadinessOptions(Options):
    timeout: float = Field(default=5, gt=0, le=120)
    canvas_timeout: float = Field(default=30, gt=0, le=180)
    quiet_ms: int = Field(default=300, ge=0, le=5000)
    navigation_min_ms: int = Field(default=750, ge=0, le=10000)
    poll_interval: float = Field(default=0.1, gt=0, le=2)
    allow_degraded_dom: bool = True
