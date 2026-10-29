from urllib.parse import quote_plus

from harnessed import Inject, Plugin, tool

from browserrig.browser.errors import BrowserError
from browserrig.browser.tab import Tab, validated_url
from browserrig.events import (
    NavigationStartedEvent,
)
from browserrig.kinds import ActionKind

from .execution import Actions, Effect


class NavigationTools(Plugin):
    @tool(description="Navigate the active tab to an HTTP(S) URL.")
    async def navigate(
        self,
        url: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        """Navigate the active tab to an HTTP(S) URL."""
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
        """Search the web with DuckDuckGo in the active tab."""
        return await self.navigate(
            f"https://duckduckgo.com/?q={quote_plus(query)}",
            actions=actions,
        )

    @tool(description="Go to the previous browser history entry.")
    async def go_back(self, *, actions: Inject[Actions]) -> str:
        """Go to the previous browser history entry."""

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
        """Reload the active tab."""

        async def reload(tab: Tab) -> Effect:
            await tab.cdp.page.reload()
            return Effect("Reload executed.")

        return await actions.run(
            kind=ActionKind.NAVIGATE,
            operation=reload,
        )
