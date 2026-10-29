from harnessed import Inject, Plugin, tool

from browserrig.browser.base import Browser
from browserrig.browser.models import TabInfo
from browserrig.browser.tab import Tab
from browserrig.core.kinds import ActionKind, ReadinessPhase
from browserrig.readiness.plugin import Readiness

from .execution import Actions, Effect


class TabTools(Plugin, needs=(Actions, Browser, Readiness)):
    _browser: Inject[Browser]
    _readiness: Inject[Readiness]

    @tool(readonly=True, description="List controlled tabs and identify the active tab.")
    async def list_tabs(self) -> tuple[TabInfo, ...]:
        return await self._browser.tabs()

    @tool(description="Open and activate a new tab.")
    async def open_tab(
        self,
        url: str = "about:blank",
        *,
        actions: Inject[Actions],
    ) -> str:
        async def open_tab(_tab: Tab) -> Effect:
            opened = await self._browser.open_tab(url)
            await self._readiness.wait(opened, phase=ReadinessPhase.NAVIGATION)
            return Effect(f"Opened tab {opened.id}.")

        return await actions.run(kind=ActionKind.TAB, operation=open_tab, settle=False)

    @tool(description="Activate one listed tab by its stable target ID.")
    async def switch_tab(
        self,
        target_id: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def switch(_tab: Tab) -> Effect:
            selected = await self._browser.activate_tab(target_id)
            await self._readiness.wait(selected)
            return Effect(f"Activated tab {selected.id}.")

        return await actions.run(kind=ActionKind.TAB, operation=switch, settle=False)

    @tool(description="Close a controlled tab. A remaining tab is explicitly selected if needed.")
    async def close_tab(
        self,
        target_id: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def close(_tab: Tab) -> Effect:
            selected = await self._browser.close_tab(target_id)
            return Effect(f"Tab closed. Active tab: {selected.id}.")

        return await actions.run(kind=ActionKind.TAB, operation=close, settle=False)
