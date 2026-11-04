import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from harnessed import (
    Agent,
    Context,
    Inject,
    Plugin,
    PluginOrder,
    SessionLog,
    SystemPrompt,
)
from harnessed.testing import ScriptedModel

from browserrig import Browser
from browserrig.browser import BrowserEvents
from browserrig.core import ReadinessStatus
from browserrig.input import Input
from browserrig.observation import BrowserPerception, DomReferences
from browserrig.readiness import Readiness, ReadinessReport
from browserrig.scripts import DOMProbe


class FakeTab:
    def __init__(self):
        self.input = self
        self.id = "tab-1"
        self.document_id = "doc-1"
        self.url = "https://example.org/"
        self.title = "Example"
        self.dialog = None
        self.navigation_pending = False
        self.loading = False
        self.closed = False
        self.quiet_ms = 1000
        self.probes = 0

    async def sync_document(self):
        pass

    async def emit(self, event):
        pass

    async def main_frame(self):
        return self

    async def run(self, script, args=None):
        if script.name != "stability" or args is not None:
            raise AssertionError(f"Unexpected fake script: {script.name}")
        self.probes += 1
        await asyncio.sleep(0)
        return DOMProbe(
            loaded=True, body=True, quiet_ms=self.quiet_ms, width=1280, height=800
        )


class FakeTabs:
    async def list(self):
        return ()


class FakeBrowser:
    def __init__(self, log):
        self.id = "browser-1"
        self.active_tab = FakeTab()
        self.tabs = FakeTabs()
        self.action_lock = asyncio.Lock()
        self.log = log
        self.files = None
        self.events = BrowserEvents(self.id, self._emit)
        self.input = Input(lambda: self.active_tab.input)
        self.mouse = self.input.mouse
        self.keyboard = self.input.keyboard

    async def downloads(self):
        return ()

    async def _emit(self, event):
        # Some tests build the fake without a log and never emit.
        await self.log.emit(event)


class FakeChrome(Plugin, needs=(SessionLog,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, ctx: Context, log: Inject[SessionLog]):
        browser = FakeBrowser(log)
        self.holder["browser"] = browser
        ctx.provide(Browser, browser)
        ctx.provide(BrowserEvents, browser.events)


class FakeReadiness:
    """Report every page as ready and record the phases waited for."""

    def __init__(self):
        self.phases = []

    async def wait(self, tab, *, phase, dispatch=None):
        self.phases.append(phase)
        if dispatch is not None:
            await dispatch()
        return ReadinessReport(
            id="ready",
            target_id=tab.id,
            document_id=tab.document_id,
            phase=phase,
            status=ReadinessStatus.READY,
            duration=0,
        )


class FakeObserve:
    """Hold the last observation and capture the tab as it is."""

    def __init__(self):
        self.snapshot = None
        self.references = DomReferences()

    async def element(self, _tab, _ref):
        raise AssertionError("No fake element resolver configured")

    async def dom_element(self, tab, ref):
        return await self.element(tab, ref)

    async def capture(self, tab):
        return SimpleNamespace(
            tab_id=tab.id,
            url=tab.url,
            document_id=tab.document_id,
            fingerprint="",
            scroll_y=0,
        )


class FakeServices(Plugin, provides=True):
    """Provide fake browser services, so real tool plugins run without Chrome."""

    def __init__(self):
        super().__init__()
        self.events = []
        self.browser = FakeBrowser(SimpleNamespace(emit=self.record))
        self.readiness = FakeReadiness()
        self.observe = FakeObserve()

    async def record(self, event):
        self.events.append(event)

    async def setup(self, ctx: Context):
        ctx.provide(Browser, self.browser)
        ctx.provide(BrowserEvents, self.browser.events)
        ctx.provide(Readiness, self.readiness)
        ctx.provide(BrowserPerception, self.observe)


@asynccontextmanager
async def mounted(*plugins):
    """Start a session with `plugins` on fake services; yield the services and context."""
    services = FakeServices()
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=ScriptedModel(["Done"]),
        plugins=[services, *plugins],
    )
    async with agent.session() as session:
        yield session.ctx[FakeServices], session.ctx
