from harnessed import Context, Inject, Plugin, SessionLog

from browserrig.events import BROWSER_EVENTS, INPUT_EVENTS

from .base import Browser
from .chrome import ChromeBrowser
from .config import BrowserOptions, LaunchBrowser


class Chrome(Plugin, needs=(SessionLog,)):
    events = BROWSER_EVENTS + INPUT_EVENTS

    def __init__(self, options: BrowserOptions | None = None) -> None:
        super().__init__()
        self.options = options or LaunchBrowser()

    async def setup(self, ctx: Context, log: Inject[SessionLog]) -> None:
        browser = await ctx.enter(ChromeBrowser(self.options, emit=log.emit))
        ctx.provide(Browser, browser)
