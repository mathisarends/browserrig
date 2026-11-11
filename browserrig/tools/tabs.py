from harnessed import Plugin
from harnessed.kernel import needs

from browserrig.browser import Browser, TabInfo
from browserrig.core import ActionKind, ReadinessPhase
from browserrig.core import browser_tool as tool
from browserrig.readiness import Readiness

from .effects import Effect
from .execution import Actions
from .navigation import NEW_TAB_URL


class TabTools(Plugin, needs=(Actions,)):
    _browser = needs(Browser)
    _readiness = needs(Readiness)

    @tool(
        kind=ActionKind.LIST_TABS,
        chainable=True,
        readonly=True,
        description="List controlled tabs and identify the active tab.",
    )
    async def list_tabs(self) -> tuple[TabInfo, ...]:
        return await self._browser.tabs.list()

    @tool(
        kind=ActionKind.OPEN_TAB,
        description="Open and activate a new tab.",
    )
    async def open_tab(
        self,
        url: str = NEW_TAB_URL,
    ) -> Effect:
        opened = await self._browser.tabs.open(url)
        await self._readiness.wait(opened, phase=ReadinessPhase.NAVIGATION)
        return Effect(f"Opened tab {opened.id}.")

    @tool(
        kind=ActionKind.SWITCH_TAB,
        description="Activate a listed tab.",
    )
    async def switch_tab(
        self,
        target_id: str,
    ) -> Effect:
        selected = await self._browser.tabs.activate(target_id)
        await self._readiness.wait(selected)
        return Effect(f"Activated tab {selected.id}.")

    @tool(
        kind=ActionKind.CLOSE_TAB,
        description="Close a controlled tab. A remaining tab is explicitly selected if needed.",
    )
    async def close_tab(
        self,
        target_id: str,
    ) -> Effect:
        selected = await self._browser.tabs.close(target_id)
        return Effect(f"Tab closed. Active tab: {selected.id}.")
