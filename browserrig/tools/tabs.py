from harnessed import Inject, Plugin, tool

from browserrig.browser.models import TabInfo
from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind
from browserrig.readiness.models import ReadinessPhase

from .execution import Actions, Effect


class TabTools(Plugin, needs=(Actions,)):
    @tool(readonly=True, description="List controlled tabs and identify the active tab.")
    async def list_tabs(self, *, actions: Inject[Actions]) -> tuple[TabInfo, ...]:
        return await actions.browser.tabs()

    @tool(description="Open and activate a new tab.")
    async def open_tab(
        self,
        url: str = "about:blank",
        *,
        actions: Inject[Actions],
    ) -> str:
        async def open_tab(_tab: Tab) -> Effect:
            opened = await actions.browser.open_tab(url)
            await actions.readiness.wait(opened, phase=ReadinessPhase.NAVIGATION)
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
            selected = await actions.browser.activate_tab(target_id)
            await actions.readiness.wait(selected)
            return Effect(f"Activated tab {selected.id}.")

        return await actions.run(kind=ActionKind.TAB, operation=switch, settle=False)

    @tool(description="Close a controlled tab. A remaining tab is explicitly selected if needed.")
    async def close_tab(
        self,
        target_id: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def close(tab: Tab) -> Effect:
            await actions.browser.close_tab(target_id)
            remaining = await actions.browser.tabs()
            if tab.id == target_id and remaining:
                await actions.browser.activate_tab(remaining[0].id)
            elif not remaining:
                await actions.browser.open_tab()
            return Effect("Tab closed.")

        return await actions.run(kind=ActionKind.TAB, operation=close, settle=False)
