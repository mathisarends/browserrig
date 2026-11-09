import hashlib
from dataclasses import dataclass

import yaml
from harnessed import Plugin, PluginState, hook
from harnessed.events import ObservationsIncludedEvent
from harnessed.hooks import Next, PreStep, StepDecision
from harnessed.kernel import observes
from harnessed.models import UserMessage

from browserrig.browser import Browser, DownloadReceiving
from browserrig.files import DOWNLOADS, FileSystem, FileSystemState, FileSystemView

_SOURCE = "files"


@dataclass
class _Delivery:
    sent: str | None = None
    visible: bool = False


class FileSystemObservation(Plugin):
    """Show the workspace, the download directory and recent downloads before each step.

    Every file tool group shares it, so the model learns about downloads whichever
    group is composed. Without a browser there are no downloads, and nothing is shown.
    """

    _delivery = PluginState(_Delivery)
    _observed_browser = observes(Browser)
    _observed_workspace = observes(FileSystem)
    _receiving = observes(DownloadReceiving)

    @hook(PreStep)
    async def _before_step(
        self, event: PreStep, next_: Next[StepDecision]
    ) -> StepDecision:
        browser = self._observed_browser
        if browser is not None:
            downloads = await browser.downloads()
            receiving = self._receiving
            state = FileSystemState(
                workspace=self._observed_workspace is not None,
                download_directory=str(DOWNLOADS)
                if receiving is not None and receiving.receiving
                else None,
                downloads=downloads[-20:],
                total_downloads=len(downloads),
            )
            content = yaml.safe_dump(
                FileSystemView(file_system=state).model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
            )
            ref = hashlib.sha256(content.encode()).hexdigest()[:16]
            delivery = self._delivery
            # Resend only changes, or when the model no longer sees the last copy
            # (e.g. compaction).
            if not (delivery.visible and delivery.sent == ref):
                event.session.observe(UserMessage(content), source=_SOURCE, refs=(ref,))
                delivery.sent, delivery.visible = ref, False
        return await next_()

    @hook(ObservationsIncludedEvent)
    async def _included(self, event: ObservationsIncludedEvent) -> None:
        delivery = self._delivery
        delivery.visible = any(
            item.source == _SOURCE and delivery.sent in item.refs
            for item in event.observations
        )
