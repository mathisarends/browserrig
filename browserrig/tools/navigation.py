import asyncio
from typing import Annotated
from urllib.parse import quote_plus

from harnessed import Inject, Plugin, tool
from pydantic import Field

from browserrig.browser.errors import BrowserError
from browserrig.browser.tab import Tab, validated_url
from browserrig.events import NavigationStartedEvent, WaitingEvent
from browserrig.kinds import ActionKind

from .execution import Actions, Effect


class NavigationTools(Plugin, needs=(Actions,)):
    @tool(description="Navigate the active tab to an HTTP(S) URL.")
    async def navigate(
        self,
        url: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        validated_url(url)

        async def navigate(tab: Tab) -> Effect:
            await actions.browser.emit(NavigationStartedEvent(target_id=tab.id, url=url))
            await tab.navigate(url)
            return Effect("Navigation executed.")

        return await actions.run(
            kind=ActionKind.NAVIGATE,
            operation=navigate,
        )

    @tool(description="Search the web with DuckDuckGo in the active tab.")
    async def search(
        self,
        query: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        return await self.navigate(
            f"https://duckduckgo.com/?q={quote_plus(query)}",
            actions=actions,
        )

    @tool(description="Go to the previous browser history entry.")
    async def go_back(self, *, actions: Inject[Actions]) -> str:
        async def back(tab: Tab) -> Effect:
            history = await tab.cdp.page.get_navigation_history()
            if history.current_index < 1:
                raise BrowserError("No previous history entry")
            await tab.cdp.page.navigate_to_history_entry(
                entry_id=history.entries[history.current_index - 1].id
            )
            return Effect("Navigated back.")

        return await actions.run(
            kind=ActionKind.NAVIGATE,
            operation=back,
        )

    @tool(description="Reload the active tab.")
    async def reload(self, *, actions: Inject[Actions]) -> str:
        async def reload(tab: Tab) -> Effect:
            await tab.cdp.page.reload()
            return Effect("Reload executed.")

        return await actions.run(
            kind=ActionKind.NAVIGATE,
            operation=reload,
        )

    @tool(
        readonly=True,
        description="Wait briefly for an expected asynchronous page update, then observe again.",
    )
    async def wait(
        self,
        seconds: Annotated[float, Field(ge=0, le=10)] = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        await actions.browser.active_tab.input.emit(WaitingEvent(duration=seconds))
        await asyncio.sleep(seconds)
        return "Wait completed; observe the current state."
