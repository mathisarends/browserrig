from harnessed import Plugin
from harnessed.kernel import Scope

from .config import FileOptions
from .system import FileSystem
from .workspace import LocalWorkspace, Workspace


class Files(Plugin, slot="browserrig.files"):
    """The agent's workspace; each session opens it as the `FileSystem` service.

    Without `workspace`, each session gets a new `LocalWorkspace` under
    `.browserrig/files/`. The workspace is independent of the browser: the browser's
    `bridge` decides whether Chrome can save downloads into it and read from it.
    """

    def __init__(
        self, workspace: Workspace | None = None, *, options: FileOptions | None = None
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.options = options if options is not None else FileOptions()

    async def setup(self, ctx: Scope) -> None:
        workspace = self.workspace if self.workspace is not None else LocalWorkspace()
        files = await ctx.enter(FileSystem(workspace, self.options))
        ctx.provide(FileSystem, files)
