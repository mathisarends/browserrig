from harnessed import Context, Inject, Plugin, SessionLog
from harnessed.events import TurnStartedEvent

from browserrig.events import BROWSER_EVENTS, INPUT_EVENTS
from browserrig.files import FileSystemOptions

from .base import Browser, BrowserEvents
from .chrome import ChromeBrowser
from .config import BrowserOptions, LaunchBrowser


class Chrome(Plugin, needs=(SessionLog,)):
    events = BROWSER_EVENTS + INPUT_EVENTS

    def __init__(
        self, options: BrowserOptions | None = None, *, file_system: FileSystemOptions | None = None
    ) -> None:
        super().__init__()
        self.options = options or LaunchBrowser()
        self.file_system = file_system

    async def setup(self, ctx: Context, log: Inject[SessionLog]) -> None:
        browser = await ctx.enter(
            ChromeBrowser(self.options, file_system=self.file_system, emit=log.emit)
        )
        ctx.provide(Browser, browser)
        ctx.provide(BrowserEvents, browser.events)

        async def publish_cursor(_event: TurnStartedEvent) -> None:
            # Live subscribers often attach after setup, so seed their animation at turn start.
            await browser.mouse.publish_cursor()

        ctx.on(TurnStartedEvent, publish_cursor)
