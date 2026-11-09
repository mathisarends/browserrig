from contextlib import suppress

from harnessed import Plugin
from harnessed.kernel import PluginScope, needs, observes

from browserrig.files import FileTransfer

from .base import Browser


class DownloadReceiving(Plugin, slot="browserrig.download-receiving", provides=True):
    """Receive browser downloads in the current workspace, independently of tools.

    A transfer appearing, changing or disappearing restarts this binding without
    reopening the browser. Attached targets may track downloads without receiving them.
    """

    _browser = needs(Browser)
    _transfer = observes(FileTransfer)

    def __init__(self) -> None:
        super().__init__()
        self.receiving = False

    async def setup(self, scope: PluginScope) -> None:
        if self._transfer is not None:
            self.receiving = await self._browser.receive_downloads(self._transfer)
            if self.receiving:
                scope.effect(self._stop)

    async def _stop(self) -> None:
        self.receiving = False
        # The browser may already be closing with the session.
        with suppress(Exception):
            await self._browser.receive_downloads(None)
