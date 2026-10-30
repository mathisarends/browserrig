from harnessed import Inject, Plugin, ToolResult

from browserrig.browser.base import Browser
from browserrig.browser.models import TabInfo
from browserrig.browser.tab import Tab
from browserrig.core.kinds import ActionKind, ReadinessPhase
from browserrig.core.tools import browser_tool as tool
from browserrig.readiness.plugin import Readiness

from .execution import Actions, Effect


class TabTools(Plugin, needs=(Actions, Browser, Readiness)):
    _browser: Inject[Browser]
    _readiness: Inject[Readiness]

    @tool(
        kind=ActionKind.LIST_TABS,
        chainable=True,
        readonly=True,
        description="List controlled tabs and identify the active tab.",
    )
    async def list_tabs(self) -> tuple[TabInfo, ...]:
        return await self._browser.tabs()

    @tool(kind=ActionKind.OPEN_TAB, description="Open and activate a new tab.")
    async def open_tab(
        self,
        url: str = "about:blank",
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def open_tab(_tab: Tab) -> Effect:
            opened = await self._browser.open_tab(url)
            await self._readiness.wait(opened, phase=ReadinessPhase.NAVIGATION)
            return Effect(f"Opened tab {opened.id}.")

        return await actions.run(kind=ActionKind.OPEN_TAB, operation=open_tab, settle=False)

    @tool(
        kind=ActionKind.SWITCH_TAB, description="Activate one listed tab by its stable target ID."
    )
    async def switch_tab(
        self,
        target_id: str,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def switch(_tab: Tab) -> Effect:
            selected = await self._browser.activate_tab(target_id)
            await self._readiness.wait(selected)
            return Effect(f"Activated tab {selected.id}.")

        return await actions.run(kind=ActionKind.SWITCH_TAB, operation=switch, settle=False)

    @tool(
        kind=ActionKind.CLOSE_TAB,
        description="Close a controlled tab. A remaining tab is explicitly selected if needed.",
    )
    async def close_tab(
        self,
        target_id: str,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        async def close(_tab: Tab) -> Effect:
            selected = await self._browser.close_tab(target_id)
            return Effect(f"Tab closed. Active tab: {selected.id}.")

        return await actions.run(kind=ActionKind.CLOSE_TAB, operation=close, settle=False)
