import asyncio
from functools import partial
from typing import Annotated
from urllib.parse import quote_plus, urljoin, urlsplit

from harnessed import Instructions, Plugin, SystemPrompt
from harnessed.kernel import needs
from pydantic import Field

from browserrig.browser import Browser, BrowserEvents, Tab, validated_url
from browserrig.core import (
    ActionKind,
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


_INSTRUCTIONS = Instructions(
    title="Browser navigation and web search",
    text=(
        "When an observation shows a link with a ref, follow it with click(ref=...). "
        "The displayed URL identifies the destination; use the ref to open it. "
        "This also applies to search results and links in above/below previews, since "
        "click scrolls the target into view. Use click(ref=..., new_tab=True) to keep "
        "the current page open. When already on DuckDuckGo with an observed search field, "
        "enter or revise the query there with type_text(ref=..., text=...), then submit "
        "with send_keys(key='Enter') or click the observed search button. "
        "Use search(query=...) to start a DuckDuckGo web search from another site, "
        "or when no usable search field is observed. "
        "Reserve navigate(url=...) for an initial URL or a known destination without "
        "a usable observed link ref."
    ),
)


class NavigationTools(Plugin):
    _browser = needs(Browser)
    _actions = needs(Actions)
    _events = needs(BrowserEvents)
    _readiness = needs(Readiness)

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @tool(
        kind=ActionKind.NAVIGATE,
        dispatch_tracked=True,
        description=(
            "Navigate to an HTTP(S) URL in the active tab, or in a new tab with new_tab=true. "
            "A path starting with / opens on the active page's site."
        ),
    )
    async def navigate(
        self,
        url: str,
        new_tab: bool = False,
    ) -> Effect:
        url = site_url(url, self._browser.active_tab.url)
        return await self._navigate(url, typed=typed_address(url), new_tab=new_tab)

    @tool(
        kind=ActionKind.SEARCH,
        dispatch_tracked=True,
        description="Search the web with DuckDuckGo in the active tab.",
    )
    async def search(
        self,
        query: str,
    ) -> Effect:
        return await self._navigate(
            f"https://duckduckgo.com/?q={quote_plus(query)}",
            typed=query,
        )

    @tool(
        kind=ActionKind.GO_BACK, description="Go to the previous browser history entry."
    )
    async def go_back(self) -> Effect:
        if not await self._actions.dispatch(partial(self._actions.tab.go_back)):
            raise BrowserError("No previous history entry")
        return Effect("Navigated back.")

    @tool(
        kind=ActionKind.GO_FORWARD,
        dispatch_tracked=True,
        description=(
            "Go to the next browser history entry. Reports an error if forward navigation "
            "is unavailable."
        ),
    )
    async def go_forward(self) -> Effect:
        tab = self._actions.tab
        if not await tab.can_go_forward():
            raise BrowserError("Cannot go forward: no next history entry")
        if not await self._actions.dispatch(partial(tab.go_forward)):
            raise BrowserError("Cannot go forward: no next history entry")
        return Effect("Navigated forward.")

    @tool(kind=ActionKind.RELOAD, description="Reload the active tab.")
    async def reload(self) -> Effect:
        await self._actions.dispatch(partial(self._actions.tab.reload))
        return Effect("Reload executed.")

    @tool(
        kind=ActionKind.WAIT,
        dispatch_tracked=True,
        readonly=True,
        description=(
            "Wait briefly for an expected asynchronous page update; the next observation shows it."
        ),
    )
    async def wait(
        self,
        seconds: Annotated[float, Field(ge=0, le=10)] = 1,
    ) -> str:
        await self._actions.stage(
            WaitIntent(seconds),
            self._browser.active_tab,
            partial(self._pause, seconds),
        )
        return "Wait completed; the next observation shows the current state."

    async def _pause(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def _navigate(
        self,
        url: str,
        *,
        typed: str,
        new_tab: bool = False,
    ) -> Effect:
        validated_url(url)
        tab = self._actions.tab
        if new_tab:
            # An empty tab first, so the address can be entered in a fresh tab.
            tab = await self._browser.tabs.open()
            await self._readiness.wait(
                tab,
                phase=ReadinessPhase.NAVIGATION,
                dispatch=partial(self._load, tab, url, typed),
            )
            return Effect(f"Opened tab {tab.id} and navigated.")
        await self._load(tab, url, typed)
        return Effect("Navigation executed.")

    async def _load(self, tab: Tab, url: str, typed: str) -> None:
        await self._actions.stage(
            NavigateIntent(url, typed),
            tab,
            partial(self._dispatch_navigation, tab, url, typed),
        )

    async def _dispatch_navigation(self, tab: Tab, url: str, typed: str) -> None:
        await self._events.emit(
            NavigationStartedEvent(target_id=tab.id, url=url, typed=typed)
        )
        await tab.navigate(url)


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
