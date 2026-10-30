import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify.domains.page import FrameStartedLoadingEvent, FrameStoppedLoadingEvent

from browserrig.browser import favicon
from browserrig.browser.favicon import load_favicon
from browserrig.browser.tab import Tab
from browserrig.events import TabUpdatedEvent
from browserrig.scripts.models import TabStrip
from browserrig.tools.navigation import site_url, typed_address

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
        ("/search?q=a#top", "http://localhost:8000/x/y", "http://localhost:8000/search?q=a#top"),
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
            load_network_resource=AsyncMock(return_value=SimpleNamespace(resource=resource))
        ),
        io=SimpleNamespace(read=AsyncMock(), close=AsyncMock()),
    )
    assert await load_favicon(cdp, "frame", "https://example.org/favicon.ico") == ""
    cdp.io.read.assert_not_awaited()
    cdp.io.close.assert_awaited_once_with(handle="stream")


async def test_tab_publishes_loading_then_the_settled_icon_once(monkeypatch):
    events = []
    tab = Tab("tab", SimpleNamespace(), emit=AsyncMock(side_effect=events.append))
    tab.url, tab.title = "https://example.org/", "example.org"
    strip = TabStrip(title="Example", icon="https://example.org/icon.png")
    frame = SimpleNamespace(id="tab", run=AsyncMock(return_value=strip))
    monkeypatch.setattr(tab, "main_frame", AsyncMock(return_value=frame))
    load = AsyncMock(return_value="data:image/png;base64,AA==")
    monkeypatch.setattr("browserrig.browser.tab.load_favicon", load)

    await tab.handle(FrameStartedLoadingEvent(frame_id="tab"))
    await tab.handle(FrameStartedLoadingEvent(frame_id="tab"))
    await tab.handle(FrameStartedLoadingEvent(frame_id="child"))
    await tab.handle(FrameStoppedLoadingEvent(frame_id="tab"))
    assert tab._strip_task is not None  # pylint: disable=protected-access
    await tab._strip_task  # pylint: disable=protected-access
    await tab.handle(FrameStoppedLoadingEvent(frame_id="tab"))
    await tab._strip_task  # pylint: disable=protected-access

    # The document title arrives before the icon has loaded.
    states = [(event.loading, event.title, event.favicon) for event in events]
    assert all(isinstance(event, TabUpdatedEvent) for event in events)
    assert states == [
        (True, "example.org", ""),
        (False, "example.org", ""),
        (False, "Example", ""),
        (False, "Example", "data:image/png;base64,AA=="),
    ]
    load.assert_awaited_once()


async def test_a_discarded_tab_stops_resolving_its_icon(monkeypatch):
    tab = Tab("tab", SimpleNamespace(), emit=AsyncMock())
    started = asyncio.Event()

    async def main_frame():
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(tab, "main_frame", main_frame)
    tab.refresh_strip()
    task = tab._strip_task  # pylint: disable=protected-access
    await started.wait()
    tab.discard()
    with pytest.raises(asyncio.CancelledError):
        await task
