from harnessed import Context, Inject, Plugin
from harnessed.core.session.session import SessionLog

from browserrig.events import BROWSER_EVENTS

from .base import Browser
from .chrome import ChromeBrowser
from .config import BrowserOptions, LaunchBrowser


class Chrome(Plugin):
    """Mount one independently owned Chrome connection per Harnessed session."""

    events = BROWSER_EVENTS

    def __init__(self, options: BrowserOptions | None = None) -> None:
        super().__init__()
        self.options = options or LaunchBrowser()

    async def setup(self, ctx: Context, log: Inject[SessionLog]) -> None:
        browser = await ctx.enter(ChromeBrowser(self.options, emit=log.emit))
        ctx.provide(Browser, browser)
