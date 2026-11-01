from dataclasses import dataclass

from harnessed import Context, Inject, Plugin, SessionLog
from harnessed.kernel import Event

from browserrig.events import BROWSER_EVENTS

from .base import Browser, BrowserEvents
from .chrome import ChromeBrowser
from .config import BrowserOptions, Launch
from .tab import Tab


class Chrome(Plugin, slot="browserrig.browser", needs=(SessionLog,)):
    events = BROWSER_EVENTS

    def __init__(self, options: BrowserOptions | None = None) -> None:
        super().__init__()
        self.options = options or Launch()

    async def setup(self, ctx: Context, log: Inject[SessionLog]) -> None:
        async def tab_changed(tab: Tab, settled: bool) -> None:
            await ctx.dispatch(TabChanged(tab, settled))

        browser = await ctx.enter(
            ChromeBrowser(
                self.options,
                emit=log.emit,
                on_tab_change=tab_changed,
            )
        )
        ctx.provide(Browser, browser)
        ctx.provide(BrowserEvents, browser.events)


@dataclass(frozen=True)
class TabChanged(Event[None]):
    """`tab` may show a new url, title or loading state, or has closed.

    `settled` marks a page that stopped loading, so its document can be read.
    """

    tab: Tab
    settled: bool
