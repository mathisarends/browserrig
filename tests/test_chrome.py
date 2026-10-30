# Listener and target ownership are verified through internal lifecycle methods.
# pylint: disable=protected-access

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from cdpify import ReceivedEvent
from cdpify.domains.browser import DownloadWillBeginEvent
from cdpify.domains.page import JavascriptDialogOpeningEvent

from browserrig import ChromeBrowser, ConnectBrowser
from browserrig.browser.tab import Tab
from browserrig.events import (
    DialogOpenedEvent,
    DisconnectedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)


async def test_event_handler_failure_does_not_stop_subscription(monkeypatch, caplog):
    browser, _ = _browser()
    handle = AsyncMock(side_effect=[RuntimeError("popup vanished"), None])
    monkeypatch.setattr(browser, "_handle", handle)
    items = [ReceivedEvent("first", None), ReceivedEvent("second", "session")]
    await browser._consume(_Subscription(items))
    assert handle.await_count == 2
    assert browser._failure is None
    assert "popup vanished" in caplog.text


async def test_root_events_reach_downloads_and_session_events_reach_their_tab():
    browser, events = _browser()
    tab = await browser._attach("tab")
    dialog = JavascriptDialogOpeningEvent(
        url="about:blank",
        frame_id="frame",
        message="Sure?",
        type="confirm",
        has_browser_handler=False,
    )
    await browser._handle(dialog, "session")
    await browser._handle(dialog, "unknown-session")
    await browser._handle(
        DownloadWillBeginEvent(
            frame_id="frame", guid="id", url="https://example.org", suggested_filename="a.txt"
        ),
        None,
    )
    assert tab.dialog == ("confirm", "Sure?")
    opened = [event for event in events if isinstance(event, DialogOpenedEvent)]
    assert [(event.target_id, event.document_id) for event in opened] == [("tab", "doc")]
    assert [download.id for download in await browser.downloads()] == ["id"]


async def test_subscription_failure_is_fatal_but_cancellation_propagates():
    browser, _ = _browser()
    failure = RuntimeError("connection lost")
    await browser._consume(_Subscription([], failure))
    assert browser._failure is failure
    with pytest.raises(asyncio.CancelledError):
        await browser._consume(_Subscription([], asyncio.CancelledError()))


async def test_concurrent_attaches_publish_exactly_one_open_event():
    browser, events = _browser()
    first, second = await asyncio.gather(
        browser._attach("popup", opened=True), browser._attach("popup", opened=True)
    )
    assert first is second
    browser.client.target.attach_to_target.assert_awaited_once()
    assert len([event for event in events if isinstance(event, TabOpenedEvent)]) == 1


async def test_close_forgets_sessions_and_ignores_stale_target_listing(monkeypatch):
    browser, events = _browser()
    closed = await browser._attach("closing")
    remaining = Tab("remaining", SimpleNamespace())
    browser._active = closed.id
    browser.client.target.get_targets.return_value = SimpleNamespace(
        target_infos=[
            SimpleNamespace(target_id=tid, type="page", title="", url="about:blank")
            for tid in ("closing", "remaining")
        ]
    )
    browser._tabs[remaining.id] = remaining
    activate = AsyncMock(return_value=remaining)
    monkeypatch.setattr(browser, "activate_tab", activate)
    assert await browser.close_tab(closed.id) is remaining
    activate.assert_awaited_once_with("remaining")
    assert closed.closed and closed.id not in browser._tabs
    assert "session" not in browser._sessions
    await browser._forget(closed.id)
    assert len([event for event in events if isinstance(event, TabClosedEvent)]) == 1


async def test_failed_startup_does_not_emit_disconnected():
    browser, events = _browser()
    await browser.aclose()
    assert not any(isinstance(event, DisconnectedEvent) for event in events)


async def test_frame_cache_is_action_scoped_and_invalidated_by_layout_and_document(monkeypatch):
    browser, _ = _browser()
    tab = await browser._attach("tab")
    browser.client.target.get_targets.return_value = SimpleNamespace(target_infos=[])
    discover = AsyncMock(return_value=((), ()))
    monkeypatch.setattr("browserrig.browser.chrome.discover_frames", discover)
    with tab.input.action("action"):
        await tab.frames()
        await tab.frames()
        assert discover.await_count == 1
        tab.invalidate_frames()
        await tab.frames()
        assert discover.await_count == 2
        tab.document_id = "another-document"
        await tab.frames()
        assert discover.await_count == 3
    await tab.frames()
    await tab.frames()
    assert discover.await_count == 5


async def test_main_frame_query_does_not_update_document_metadata():
    browser, _ = _browser()
    tab = await browser._attach("tab")
    frame = SimpleNamespace(id="frame", loader_id="new-document", url="https://example.org")
    tab.cdp.page.get_frame_tree.return_value = SimpleNamespace(
        frame_tree=SimpleNamespace(frame=frame)
    )
    await tab.main_frame()
    assert tab.document_id == "doc" and tab.url == "about:blank"
    await tab.sync_document()
    assert tab.document_id == "new-document" and tab.url == "https://example.org"


class _Subscription:
    def __init__(self, items, error=None):
        self.items = items
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self.items:
            yield item
        if self.error is not None:
            raise self.error


def _browser():
    events = []
    browser = ChromeBrowser(
        ConnectBrowser(endpoint="ws://localhost/devtools/browser/test"),
        emit=AsyncMock(side_effect=events.append),
    )
    browser._stack = AsyncExitStack()
    cdp = SimpleNamespace(
        page=SimpleNamespace(
            enable=AsyncMock(),
            get_frame_tree=AsyncMock(
                return_value=SimpleNamespace(
                    frame_tree=SimpleNamespace(
                        frame=SimpleNamespace(id="frame", loader_id="doc", url="about:blank")
                    )
                )
            ),
        ),
        runtime=SimpleNamespace(enable=AsyncMock()),
    )
    browser.client = SimpleNamespace(
        is_connected=True,
        session=Mock(return_value=cdp),
        target=SimpleNamespace(
            attach_to_target=AsyncMock(return_value=SimpleNamespace(session_id="session")),
            detach_from_target=AsyncMock(),
            close_target=AsyncMock(),
            get_targets=AsyncMock(),
        ),
    )
    return browser, events
