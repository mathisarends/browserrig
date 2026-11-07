import asyncio
import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify.domains.input import MouseButton
from cdpify.domains.page import (
    FrameStartedLoadingEvent,
    FrameStartedNavigatingEvent,
    FrameStoppedLoadingEvent,
    JavascriptDialogClosedEvent,
    JavascriptDialogOpeningEvent,
    LifecycleEventEvent,
)
from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig.browser import Tab, TabChanged, favicon
from browserrig.browser.favicon import load_favicon
from browserrig.choreography import TabStrip as TabStripPlugin
from browserrig.core import MouseEventKind, Point
from browserrig.events import TabUpdatedEvent
from browserrig.scripts import TabStrip
from browserrig.tools.navigation import site_url, typed_address
from tests.fakes import FakeServices

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


@pytest.mark.parametrize(
    "url, typed",
    [
        ("https://example.org/", "example.org"),
        ("http://localhost:8000", "localhost:8000"),
        ("https://www.example.org/docs?q=1", "www.example.org/docs?q=1"),
        ("https://example.org/?q=1", "example.org/?q=1"),
        ("about:blank", "about:blank"),
    ],
)
def test_typed_address_drops_only_what_a_person_would_not_type(url, typed):
    assert typed_address(url) == typed


@pytest.mark.parametrize(
    "url, current, resolved",
    [
        (
            "/wiki/Voyager_1",
            "https://de.wikipedia.org/wiki/Voyager_2",
            "https://de.wikipedia.org/wiki/Voyager_1",
        ),
        (
            "/search?q=a#top",
            "http://localhost:8000/x/y",
            "http://localhost:8000/search?q=a#top",
        ),
        ("https://example.org/", "https://de.wikipedia.org/", "https://example.org/"),
        ("//example.org/", "https://de.wikipedia.org/", "//example.org/"),
        ("/wiki/Voyager_1", "about:blank", "/wiki/Voyager_1"),
    ],
)
def test_site_paths_resolve_only_against_web_pages(url, current, resolved):
    assert site_url(url, current) == resolved


@pytest.mark.parametrize(
    "data, media_type",
    [
        (_PNG, "image/png"),
        (b"\x00\x00\x00\x1cftypavif" + b"\x00" * 8, "image/avif"),
        (b"<!-- Generator: Illustrator --><svg xmlns='x'/>", "image/svg+xml"),
        (b"\xef\xbb\xbf<?xml version='1.0'?>\n<svg/>", "image/svg+xml"),
        (b"<?xml version='1.0'?><html><body><svg/></body></html>", None),
        (b"<!doctype html><title>Not found</title>", None),
    ],
)
def test_icon_type_comes_from_the_bytes(data, media_type):
    assert favicon._media_type(data) == media_type  # pylint: disable=protected-access


async def test_inline_data_icons_are_decoded_without_a_fetch():
    cdp = SimpleNamespace(network=SimpleNamespace(load_network_resource=AsyncMock()))
    emoji = "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22><text>%F0%9F%8E%AF</text></svg>"
    icon = await load_favicon(cdp, "frame", emoji)
    assert icon.startswith("data:image/svg+xml;base64,")
    assert "🎯".encode() in base64.b64decode(icon.split(",", 1)[1])
    encoded = "data:image/png;base64," + base64.b64encode(_PNG).decode()
    assert await load_favicon(cdp, "frame", encoded) == encoded
    assert await load_favicon(cdp, "frame", "data:text/html,<p>hi</p>") == ""
    cdp.network.load_network_resource.assert_not_awaited()


async def test_error_status_skips_the_body_and_still_closes_the_stream():
    resource = SimpleNamespace(success=True, stream="stream", http_status_code=404.0)
    cdp = SimpleNamespace(
        network=SimpleNamespace(
            load_network_resource=AsyncMock(
                return_value=SimpleNamespace(resource=resource)
            )
        ),
        io=SimpleNamespace(read=AsyncMock(), close=AsyncMock()),
    )
    assert await load_favicon(cdp, "frame", "https://example.org/favicon.ico") == ""
    cdp.io.read.assert_not_awaited()
    cdp.io.close.assert_awaited_once_with(handle="stream")


async def test_navigation_pending_ends_at_its_dom_content_loaded_before_all_resources():
    tab = Tab("tab", SimpleNamespace())
    tab.document_id = "old"
    await tab.handle(
        FrameStartedNavigatingEvent(
            frame_id="tab",
            loader_id="new",
            url="https://example.org/new",
            navigation_type="differentDocument",
        )
    )
    await tab.handle(FrameStartedLoadingEvent(frame_id="tab"))
    assert tab.navigation_pending and tab.loading
    # An old document or child frame cannot complete this main-frame navigation.
    for frame, loader in [("tab", "old"), ("child", "new")]:
        await tab.handle(
            LifecycleEventEvent(
                frame_id=frame,
                loader_id=loader,
                name="DOMContentLoaded",
                timestamp=1,
            )
        )
        assert tab.navigation_pending
    tab.document_id = "new"
    await tab.handle(
        LifecycleEventEvent(
            frame_id="tab",
            loader_id="new",
            name="DOMContentLoaded",
            timestamp=2,
        )
    )
    assert not tab.navigation_pending and tab.loading


async def test_tab_strip_publishes_loading_then_the_settled_icon_once(monkeypatch):
    events = []
    watched = _Watched(emit=AsyncMock(side_effect=events.append))
    tab = watched.tab
    # Already loading when the strip starts watching.
    tab.url, tab.title, tab.loading = "https://example.org/", "example.org", True
    icon = "https://example.org/icon.png"
    strips = [
        TabStrip(title="Example", icon=icon),
        TabStrip(title="Renamed", icon=icon),
    ]
    monkeypatch.setattr(tab, "read_strip", AsyncMock(side_effect=strips))
    load = AsyncMock(return_value="data:image/png;base64,AA==")
    monkeypatch.setattr(tab, "load_icon", load)

    async with watched.mounted():
        await tab.handle(FrameStartedLoadingEvent(frame_id="tab"))
        await tab.handle(FrameStartedLoadingEvent(frame_id="child"))
        await tab.handle(FrameStoppedLoadingEvent(frame_id="tab"))
        await _until(lambda: len(events) == 4)
        # A later read with the same icon updates the title without fetching the icon.
        await tab.handle(FrameStoppedLoadingEvent(frame_id="tab"))
        await _until(lambda: len(events) == 5)
        # A newer title from Chrome replaces the one the document declared.
        tab.title = "From Chrome"
        await tab.report_change()

    # The document title arrives before the icon has loaded.
    states = [(event.loading, event.title, event.favicon) for event in events]
    assert all(isinstance(event, TabUpdatedEvent) for event in events)
    assert states == [
        (True, "example.org", ""),
        (False, "example.org", ""),
        (False, "Example", ""),
        (False, "Example", "data:image/png;base64,AA=="),
        (False, "Renamed", "data:image/png;base64,AA=="),
        (False, "From Chrome", "data:image/png;base64,AA=="),
    ]
    load.assert_awaited_once_with(icon)


async def test_a_closed_tab_stops_resolving_its_strip(monkeypatch):
    watched = _Watched(emit=AsyncMock())
    tab = watched.tab
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def read_strip():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(tab, "read_strip", read_strip)
    async with watched.mounted():
        await tab.handle(FrameStoppedLoadingEvent(frame_id="tab"))
        await asyncio.wait_for(started.wait(), 5)
        await tab.discard()
        await asyncio.wait_for(cancelled.wait(), 5)


async def test_a_tab_without_a_strip_reads_and_reports_nothing(monkeypatch):
    emit = AsyncMock()
    tab = Tab("tab", SimpleNamespace(), emit=emit)
    read = AsyncMock()
    monkeypatch.setattr(tab, "read_strip", read)
    await tab.handle(FrameStartedLoadingEvent(frame_id="tab"))
    await tab.handle(FrameStoppedLoadingEvent(frame_id="tab"))
    assert not tab.loading
    emit.assert_not_awaited()
    read.assert_not_awaited()


async def test_input_that_opens_a_dialog_returns_without_waiting_for_its_reply():
    held = asyncio.get_running_loop().create_future()

    async def dispatch_mouse_event(**_):
        await held

    cdp = SimpleNamespace(
        input=SimpleNamespace(dispatch_mouse_event=dispatch_mouse_event),
        page=SimpleNamespace(
            get_frame_tree=AsyncMock(side_effect=AssertionError("blocked"))
        ),
    )
    tab = Tab("tab", cdp)
    click = asyncio.create_task(
        tab.input.dispatch_mouse(
            MouseEventKind.RELEASED,
            Point(x=1, y=2),
            button=MouseButton.LEFT,
            buttons=0,
            click_count=1,
        )
    )
    await asyncio.sleep(0)
    assert not click.done()
    await tab.handle(_dialog())
    await asyncio.wait_for(click, 1)
    # The page answers nothing while the dialog is open, so the document is kept as is.
    await tab.sync_document()
    held.set_exception(RuntimeError("reply after the dialog closed"))
    await tab.handle(
        JavascriptDialogClosedEvent(frame_id="tab", result=True, user_input="")
    )
    assert tab.dialog is None


def _dialog() -> JavascriptDialogOpeningEvent:
    return JavascriptDialogOpeningEvent(
        url="about:blank",
        frame_id="tab",
        message="Hi",
        type="alert",
        has_browser_handler=False,
    )


class _Watched:
    """A tab whose changes reach a mounted `TabStrip`, the way Chrome passes them on."""

    def __init__(self, *, emit):
        self.tab = Tab("tab", SimpleNamespace(), emit=emit, on_change=self._changed)
        self._ctx = None

    async def _changed(self, tab, settled):
        assert self._ctx is not None
        await self._ctx.dispatch(TabChanged(tab, settled))

    @asynccontextmanager
    async def mounted(self):
        services = FakeServices()
        agent = Agent(
            model=ScriptedModel(["Done"]),
            plugins=[services, TabStripPlugin()],
        )
        async with agent.session() as session:
            session.scope[FakeServices].browser.active_tab = self.tab
            self._ctx = session.scope
            yield


async def _until(condition):
    async with asyncio.timeout(5):
        while not condition():
            await asyncio.sleep(0)
