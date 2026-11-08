from harnessed import Plugin
from harnessed.kernel import PluginScope, observes

from .bridge import FileBridge
from .config import FileOptions
from .system import FileSystem
from .transfer import FileTransfer
from .workspace import LocalWorkspace, Workspace


class Files(Plugin, slot="browserrig.files"):
    """The agent's workspace; each session opens it as the `FileSystem` service.

    Without `workspace`, each session gets a new `LocalWorkspace` under
    `.browserrig/files/`. The workspace is independent of the browser; the bridge
    configured with Chrome decides whether Chrome can read and write its files.
    """

    def __init__(
        self, workspace: Workspace | None = None, *, options: FileOptions | None = None
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.options = options if options is not None else FileOptions()

    async def setup(self, scope: PluginScope) -> None:
        workspace = self.workspace if self.workspace is not None else LocalWorkspace()
        files = await scope.enter(FileSystem(workspace, self.options))
        scope.provide(FileSystem, files)


class FileTransfers(Plugin):
    """Bind a browser host's bridge to the session's optional workspace.

    Workspace changes replace the transfer service without reopening the browser.
    The browser pack includes this provider; Chrome publishes its configured bridge.
    Explicit compositions add this plugin alongside Chrome and Files.
    """

    _workspace = observes(FileSystem)
    _bridge = observes(FileBridge)

    def __init__(self, bridge: FileBridge | None = None) -> None:
        super().__init__()
        self.bridge = bridge

    async def setup(self, scope: PluginScope) -> None:
        bridge = self.bridge if self.bridge is not None else self._bridge
        if self._workspace is not None and bridge is not None:
            scope.provide(FileTransfer, FileTransfer(self._workspace, bridge))
