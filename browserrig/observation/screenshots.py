from harnessed import Instructions, Plugin, SystemPrompt
from harnessed.kernel import PluginScope, needs

from .config import ScreenshotPolicy, ScreenshotTrigger
from .plugin import BrowserPerception
from .retention import ImageRetention, TrimInBatches


class Screenshots(Plugin, slot="browserrig.screenshots"):
    """Add viewport screenshots to browser observations.

    EACH_STEP captures before every model step. ON_REQUEST captures when a tool asks,
    and on each new page while no page model supplies text.
    """

    _perception = needs(BrowserPerception)

    def __init__(
        self,
        *,
        trigger: ScreenshotTrigger = ScreenshotTrigger.ON_REQUEST,
        skip_unchanged: bool = True,
        retention: ImageRetention | None = None,
    ) -> None:
        super().__init__()
        self.policy = ScreenshotPolicy(
            trigger=trigger,
            skip_unchanged=skip_unchanged,
            retention=retention if retention is not None else TrimInBatches(),
        )

    async def setup(self, scope: PluginScope) -> None:
        scope.effect(self._perception.use_screenshots(self.policy))

    def instructions(self) -> SystemPrompt:
        lines = []
        if self.policy.trigger == ScreenshotTrigger.EACH_STEP:
            lines.append("A screenshot is captured before each model step.")
        if self.policy.skip_unchanged:
            lines.append("Unchanged images may be reused.")
        lines.append("Screenshots belong to the observation they were captured with.")
        return SystemPrompt(
            Instructions(title="Browser screenshots", text=" ".join(lines))
        )
