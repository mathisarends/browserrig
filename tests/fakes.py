import asyncio

from harnessed import Context, Inject, Plugin, SessionLog

from browserrig import Browser
from browserrig.browser.base import BrowserEvents
from browserrig.scripts.models import DOMProbe


class FakeTab:
    def __init__(self):
        self.id = "tab-1"
        self.document_id = "doc-1"
        self.url = "https://example.org/"
        self.dialog = None
        self.quiet_ms = 1000
        self.probes = 0

    async def sync_document(self):
        pass

    async def main_frame(self):
        return self

    async def run(self, script, args=None):
        if script.name != "stability" or args is not None:
            raise AssertionError(f"Unexpected fake script: {script.name}")
        self.probes += 1
        await asyncio.sleep(0)
        return DOMProbe(loaded=True, body=True, quiet_ms=self.quiet_ms, width=1280, height=800)


class FakeBrowser:
    def __init__(self, log):
        self.id = "browser-1"
        self.active_tab = FakeTab()
        self.action_lock = asyncio.Lock()
        self.log = log
        self.files = None
        self.events = BrowserEvents(self.id, self._emit)

    async def _emit(self, event):
        # Some tests build the fake without a log and never emit.
        await self.log.emit(event)

    async def downloads(self):
        return ()


class FakeChrome(Plugin, needs=(SessionLog,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, ctx: Context, log: Inject[SessionLog]):
        browser = FakeBrowser(log)
        self.holder["browser"] = browser
        ctx.provide(Browser, browser)
        ctx.provide(BrowserEvents, browser.events)
