from harnessed import Plugin
from harnessed.kernel import PluginScope

from .actions import ActionContext
from .coordination import BrowserCoordination


class Runtime(Plugin, slot="browserrig.runtime"):
    """Provide session-local action correlation and exclusive runtime control."""

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(ActionContext, ActionContext())
        scope.provide(BrowserCoordination, BrowserCoordination())
