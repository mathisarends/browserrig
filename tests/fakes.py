import asyncio
from dataclasses import replace

from harnessed import Context, Inject, Plugin, SessionLog

from browserrig import Browser


class FakeTab:
    def __init__(self):
        self.id = "tab-1"
        self.document_id = "doc-1"
        self.url = "https://example.org/"
        self.dialog = None
        self.quiet_ms = 1000
        self.probes = 0

    async def main_frame(self):
        return self

    async def evaluate(self, _expression):
        self.probes += 1
        await asyncio.sleep(0)
        return {
            "loaded": True,
            "body": True,
            "quiet_ms": self.quiet_ms,
            "width": 1280,
            "height": 800,
        }


class FakeBrowser:
    def __init__(self, log):
        self.id = "browser-1"
        self.active_tab = FakeTab()
        self.action_lock = asyncio.Lock()
        self.log = log

    async def emit(self, event):
        await self.log.emit(replace(event, browser_id=self.id))


class FakeChrome(Plugin):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, ctx: Context, log: Inject[SessionLog]):
        browser = FakeBrowser(log)
        self.holder["browser"] = browser
        ctx.provide(Browser, browser)
