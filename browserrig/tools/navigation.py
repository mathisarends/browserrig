import asyncio
from typing import Annotated
from urllib.parse import quote_plus

from harnessed import Inject, Plugin, tool
from pydantic import Field

from browserrig.browser.base import Browser, BrowserEvents
from browserrig.browser.tab import Tab, validated_url
from browserrig.core.errors import BrowserError
from browserrig.core.kinds import ActionKind
from browserrig.events import NavigationStartedEvent, WaitingEvent

from .execution import Actions, Effect


class NavigationTools(Plugin, needs=(Actions, Browser, BrowserEvents)):
    _browser: Inject[Browser]
    _events: Inject[BrowserEvents]

    @tool(description="Navigate the active tab to an HTTP(S) URL.")
    async def navigate(
        self,
        url: str,
        *,
        actions: Inject[Actions],
    ) -> str:
        validated_url(url)

        async def navigate(tab: Tab) -> Effect:
            await self._events.emit(NavigationStartedEvent(target_id=tab.id, url=url))
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
            if not await tab.go_back():
                raise BrowserError("No previous history entry")
            return Effect("Navigated back.")

        return await actions.run(
            kind=ActionKind.NAVIGATE,
            operation=back,
        )

    @tool(
        description=(
            "Go to the next browser history entry. Reports an error if forward navigation "
            "is unavailable."
        )
    )
    async def go_forward(self, *, actions: Inject[Actions]) -> str:
        async def check(tab: Tab) -> None:
            if not await tab.can_go_forward():
                raise BrowserError("Cannot go forward: no next history entry")

        async def forward(tab: Tab) -> Effect:
            if not await tab.go_forward():
                raise BrowserError("Cannot go forward: no next history entry")
            return Effect("Navigated forward.")

        return await actions.run(
            kind=ActionKind.NAVIGATE,
            operation=forward,
            check=check,
        )

    @tool(description="Reload the active tab.")
    async def reload(self, *, actions: Inject[Actions]) -> str:
        async def reload(tab: Tab) -> Effect:
            await tab.reload()
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
    ) -> str:
        async with self._browser.action_lock:
            await self._events.emit(WaitingEvent(duration=seconds))
            await asyncio.sleep(seconds)
        return "Wait completed; observe the current state."
