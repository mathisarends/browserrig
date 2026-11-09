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
            scope.effect(self._stop)

    async def _stop(self) -> None:
        await self._browser.receive_downloads(None)
        self.receiving = False
