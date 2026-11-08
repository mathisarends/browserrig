import asyncio
from typing import Annotated
from urllib.parse import quote_plus, urljoin, urlsplit

from harnessed import Inject, Plugin, ToolResult
from harnessed.kernel import needs
from pydantic import Field

from browserrig.browser import Browser, BrowserEvents, Tab, validated_url
from browserrig.core import (
    ActionKind,
    BrowserCoordination,
    BrowserError,
    ReadinessPhase,
)
from browserrig.core import browser_tool as tool
from browserrig.events import NavigationStartedEvent
from browserrig.readiness import Readiness

from .effects import Effect
from .execution import Actions
from .intents import NavigateIntent, WaitIntent

# Where a new tab lands when the agent gives no URL.
NEW_TAB_URL = "https://duckduckgo.com/"


class NavigationTools(Plugin, needs=(Actions,)):
    _browser = needs(Browser)
    _coordination = needs(BrowserCoordination)
    _events = needs(BrowserEvents)
    _readiness = needs(Readiness)

    @tool(
        kind=ActionKind.NAVIGATE,
        description=(
            "Navigate to an HTTP(S) URL in the active tab, or in a new tab with new_tab=true. "
            "A path starting with / opens on the active page's site."
        ),
    )
    async def navigate(
        self,
        url: str,
        new_tab: bool = False,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        url = site_url(url, self._browser.active_tab.url)
        return await self._navigate(
            url, actions, ActionKind.NAVIGATE, typed=typed_address(url), new_tab=new_tab
        )

    @tool(
        kind=ActionKind.SEARCH,
        description="Search the web with DuckDuckGo in the active tab.",
    )
    async def search(
        self,
        query: str,
        *,
        actions: Inject[Actions],
    ) -> ToolResult:
        return await self._navigate(
            f"https://duckduckgo.com/?q={quote_plus(query)}",
            actions,
            ActionKind.SEARCH,
            typed=query,
        )

    @tool(
        kind=ActionKind.GO_BACK, description="Go to the previous browser history entry."
    )
    async def go_back(self, *, actions: Inject[Actions]) -> ToolResult:
        async def back(tab: Tab) -> Effect:
            if not await tab.go_back():
                raise BrowserError("No previous history entry")
            return Effect("Navigated back.")

        return await actions.run(
            kind=ActionKind.GO_BACK,
            operation=back,
        )

    @tool(
        kind=ActionKind.GO_FORWARD,
        description=(
            "Go to the next browser history entry. Reports an error if forward navigation "
            "is unavailable."
        ),
    )
    async def go_forward(self, *, actions: Inject[Actions]) -> ToolResult:
        async def check(tab: Tab) -> None:
            if not await tab.can_go_forward():
                raise BrowserError("Cannot go forward: no next history entry")

        async def forward(tab: Tab) -> Effect:
            if not await tab.go_forward():
                raise BrowserError("Cannot go forward: no next history entry")
            return Effect("Navigated forward.")

        return await actions.run(
            kind=ActionKind.GO_FORWARD,
            operation=forward,
            check=check,
        )

    @tool(kind=ActionKind.RELOAD, description="Reload the active tab.")
    async def reload(self, *, actions: Inject[Actions]) -> ToolResult:
        async def reload(tab: Tab) -> Effect:
            await tab.reload()
            return Effect("Reload executed.")

        return await actions.run(
            kind=ActionKind.RELOAD,
            operation=reload,
        )

    @tool(
        kind=ActionKind.WAIT,
        readonly=True,
        description=(
            "Wait briefly for an expected asynchronous page update; the next observation shows it."
        ),
    )
    async def wait(
        self,
        seconds: Annotated[float, Field(ge=0, le=10)] = 1,
        *,
        actions: Inject[Actions],
    ) -> str:
        async with self._coordination.exclusive():

            async def pause() -> None:
                await asyncio.sleep(seconds)

            await actions.stage(WaitIntent(seconds), self._browser.active_tab, pause)
        return "Wait completed; the next observation shows the current state."

    async def _navigate(
        self,
        url: str,
        actions: Actions,
        kind: ActionKind,
        *,
        typed: str,
        new_tab: bool = False,
    ) -> ToolResult:
        validated_url(url)

        async def navigate(tab: Tab) -> Effect:
            async def load() -> None:
                await self._events.emit(
                    NavigationStartedEvent(target_id=tab.id, url=url, typed=typed)
                )
                await tab.navigate(url)

            await actions.stage(NavigateIntent(url, typed), tab, load)
            return Effect("Navigation executed.")

        async def navigate_new(_tab: Tab) -> Effect:
            # An empty tab first, so the address can be entered in a fresh tab.
            opened = await self._browser.tabs.open()

            async def dispatch() -> None:
                await navigate(opened)

            await self._readiness.wait(
                opened, phase=ReadinessPhase.NAVIGATION, dispatch=dispatch
            )
            return Effect(f"Opened tab {opened.id} and navigated.")

        if new_tab:
            return await actions.run(kind=kind, operation=navigate_new, settle=False)
        return await actions.run(kind=kind, operation=navigate)


def site_url(  # smelt: ignore[SMT429] -- pure, table-tested
    url: str, current: str
) -> str:
    """Resolve a site path such as ``/wiki/Page`` against the current HTTP(S) page."""
    site_path = url.startswith("/") and not url.startswith("//")
    if site_path and urlsplit(current).scheme in {"http", "https"}:
        return urljoin(current, url)
    return url


def typed_address(url: str) -> str:  # smelt: ignore[SMT429] -- pure, table-tested
    """What a person types into the address bar for `url`: no scheme, no lone trailing slash."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return url
    typed = url.split("://", 1)[1]
    if parts.path == "/" and not parts.query and not parts.fragment:
        typed = typed.removesuffix("/")
    return typed
