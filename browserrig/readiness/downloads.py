from harnessed import Inject, Plugin, hook
from harnessed.hooks import Next

from browserrig.browser import Browser
from browserrig.files import DownloadState

from .hooks import CheckReadiness, ReadinessCheck
from .plugin import Readiness


class DownloadReadiness(Plugin, needs=(Browser, Readiness)):
    """Include active downloads in the same readiness budget as page activity."""

    _browser: Inject[Browser]

    @hook(CheckReadiness)
    async def _check(
        self, _event: CheckReadiness, next_: Next[ReadinessCheck]
    ) -> ReadinessCheck:
        result = await next_()
        if not result.ready:
            return result
        active = sum(
            item.state == DownloadState.IN_PROGRESS
            for item in await self._browser.downloads()
        )
        if active:
            return ReadinessCheck(False, f"Waiting for {active} active download(s)")
        return result
