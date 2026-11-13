import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from harnessed import (
    Agent,
    Plugin,
    SessionLog,
)
from harnessed.kernel import PluginScope, needs
from harnessed.testing import ScriptedModel

from browserrig import Browser, BrowserCoordination, FileSystem
from browserrig.browser import BrowserEvents
from browserrig.browser.network import NetworkActivity
from browserrig.core import ActionContext, ReadinessPhase, ReadinessStatus
from browserrig.files import FileBridge, FileTransfers
from browserrig.input import Input, InputTargets
from browserrig.observation import BrowserPerception, DomElements, DomReferences
from browserrig.readiness import Readiness, ReadinessReport
from browserrig.scripts import DOMProbe
from browserrig.tools import Actions, Targeting


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
        self.network = NetworkActivity()
        self.viewport_revision = 0

    async def viewport_size(self):
        return (1280, 800)

    async def dispatch_mouse(self, *_args, **_kwargs):
        pass

    async def sync_document(self):
        pass

    def layout_changed(self):
        pass

    def check_navigation(self):
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
    openings = 0

    async def list(self):
        return ()

    async def opened_since(self, _mark, *, timeout=0):
        del timeout
        return None


class FakeBrowser:
    def __init__(self, log):
        self.id = "browser-1"
        self.active_tab = FakeTab()
        self.tabs = FakeTabs()
        self.log = log
        self.receiving = None
        self.events = BrowserEvents(self.id, self._emit)
        self.input_targets = SimpleNamespace(focused=lambda: self.active_tab.input)

    async def downloads(self):
        return ()

    async def receive_downloads(self, transfer):
        # Without CDP nothing is saved; the transfer is kept for staging checks.
        self.receiving = transfer
        return False

    async def _emit(self, event):
        # Some tests build the fake without a log and never emit.
        await self.log.emit(event)


class FakeChrome(Plugin, needs=(SessionLog,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    _setup_log = needs(SessionLog)

    async def setup(self, ctx: PluginScope):
        log = self._setup_log
        browser = FakeBrowser(log)
        self.holder["browser"] = browser
        actions = ActionContext()
        devices = Input(
            browser.input_targets.focused, action_id=lambda: actions.action_id
        )
        ctx.provide(ActionContext, actions)
        ctx.provide(Input, devices)
        ctx.provide(InputTargets, browser.input_targets)
        self.holder["input"] = devices
        self.holder["actions"] = actions
        coordination = BrowserCoordination()
        self.holder["coordination"] = coordination
        ctx.provide(Browser, browser)
        ctx.provide(BrowserEvents, browser.events)
        ctx.provide(BrowserCoordination, coordination)


class FakeReadiness:
    """Report every page as ready and record the phases waited for."""

    def __init__(self):
        self.phases = []

    async def wait(  # pylint: disable=unused-argument
        self, tab, *, phase=ReadinessPhase.OBSERVATION, dispatch=None, since=None
    ):
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

    def __init__(self, bridge=None):
        super().__init__()
        self.events = []
        self.browser = FakeBrowser(SimpleNamespace(emit=self.record))
        self.bridge = bridge
        self.coordination = BrowserCoordination()
        self.correlation = ActionContext()
        self.input = Input(
            self.browser.input_targets.focused,
            action_id=lambda: self.correlation.action_id,
        )
        self.readiness = FakeReadiness()
        self.observe = FakeObserve()

    async def record(self, event):
        self.events.append(event)

    async def setup(self, ctx: PluginScope):
        ctx.provide(ActionContext, self.correlation)
        ctx.provide(Input, self.input)
        ctx.provide(InputTargets, self.browser.input_targets)
        ctx.provide(Browser, self.browser)
        ctx.provide(BrowserEvents, self.browser.events)
        ctx.provide(BrowserCoordination, self.coordination)
        ctx.provide(Readiness, self.readiness)
        ctx.provide(BrowserPerception, self.observe)
        ctx.provide(DomElements, SimpleNamespace(resolve=self.observe.dom_element))
        if self.bridge is not None:
            ctx.provide(FileBridge, self.bridge)


class OpenFiles(Plugin):
    """Provide an already open file system as the session's workspace."""

    def __init__(self, files: FileSystem) -> None:
        super().__init__()
        self.files = files

    async def setup(self, ctx: PluginScope) -> None:
        ctx.provide(FileSystem, self.files)


@asynccontextmanager
async def mounted(*plugins, bridge=None, files=None):
    """Start a session with `plugins` on fake services; yield the services and context.

    `files` becomes the session's workspace; `bridge` lets the fake browser reach it.
    """
    services = FakeServices(bridge)
    targeting = (
        (Targeting(),)
        if any(isinstance(plugin, Actions) for plugin in plugins)
        and not any(isinstance(plugin, Targeting) for plugin in plugins)
        else ()
    )
    workspace = () if files is None else (OpenFiles(files),)
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=[services, *workspace, FileTransfers(), *targeting, *plugins],
    )
    async with agent.session() as session:
        yield session.scope[FakeServices], session.scope
