# Listener and target ownership are verified through internal lifecycle methods.
# pylint: disable=protected-access
import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from cdpify import ReceivedEvent
from cdpify.domains.browser import DownloadWillBeginEvent
from cdpify.domains.page import JavascriptDialogOpeningEvent
from cdpify.domains.target import (
    TargetDestroyedEvent,
    TargetInfo,
    TargetInfoChangedEvent,
)
from pydantic import ValidationError

from browserrig import ChromeBrowser, SessionSetup, Viewport
from browserrig.browser import Connect, Launch, Tab
from browserrig.browser import tabs as tabs_module
from browserrig.core import ActionContext
from browserrig.events import (
    DialogOpenedEvent,
    DisconnectedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)
from browserrig.kinds import TabGesture


@pytest.mark.parametrize(
    "options", [Launch, lambda **kwargs: Connect(endpoint="ws://localhost", **kwargs)]
)
def test_session_setup_options_validate_entries_and_freeze_the_sequence(options):
    setup = _RecordingSetup("custom", [])
    entries = [setup]
    configured = options(session_setup=entries)
    entries.clear()
    assert configured.session_setup == (setup,)
    assert options().session_setup == ()
    assert isinstance(setup, SessionSetup)
    with pytest.raises(ValidationError, match="SessionSetup"):
        options(session_setup=[object()])
    with pytest.raises(ValidationError, match="frozen"):
        configured.session_setup = ()


async def test_late_target_metadata_does_not_reattach_a_destroyed_tab():
    browser, _ = _browser(Launch())
    target = browser.client.target
    target.create_browser_context = AsyncMock(
        return_value=SimpleNamespace(browser_context_id="context")
    )
    target.dispose_browser_context = AsyncMock()
    async with AsyncExitStack() as stack:
        await browser.tabs.start(browser.client, stack)
        await browser.tabs.handle(TargetDestroyedEvent(target_id="gone"), None)
        info = TargetInfo(
            target_id="gone",
            type="page",
            title="Gone",
            url="about:blank",
            attached=False,
            can_access_opener=False,
            browser_context_id="context",
        )
        await browser.tabs.handle(TargetInfoChangedEvent(target_info=info), None)
    target.attach_to_target.assert_not_awaited()
    assert browser.tabs.focused() is None
    target.dispose_browser_context.assert_awaited_once_with(
        browser_context_id="context"
    )


@pytest.mark.parametrize("options", [Launch, Connect])
async def test_setups_run_in_order_on_new_page_and_frame_sessions(options):
    calls = []
    viewport = Viewport(width=900, height=700, scale=2)
    kwargs = {"endpoint": "ws://localhost"} if options is Connect else {}
    configured = options(
        viewport=viewport,
        session_setup=(
            _RecordingSetup("first", calls),
            _RecordingSetup("second", calls),
        ),
        **kwargs,
    )
    browser, _ = _browser(configured)
    browser.client.target.attach_to_target.side_effect = [
        SimpleNamespace(session_id="page-session"),
        SimpleNamespace(session_id="frame-session"),
    ]
    tab = await browser.tabs._attach("page")
    assert await browser.tabs._attach("page") is tab
    cdp = await browser.tabs._frame_session("frame")
    assert await browser.tabs._frame_session("frame") is cdp
    assert calls == [
        ("first", tab.cdp, False, 1),
        ("second", tab.cdp, False, 1),
        ("first", cdp, True, 1),
        ("second", cdp, True, 1),
    ]
    assert cdp.page.enable.await_count == 2
    assert cdp.runtime.enable.await_count == 2
    # Only the page session reports requests; frames reuse its readiness.
    assert cdp.network.enable.await_count == 1
    assert cdp.page.set_lifecycle_events_enabled.await_args_list == [
        call(enabled=True),
        call(enabled=True),
    ]
    cdp.emulation.set_device_metrics_override.assert_awaited_once_with(
        width=900, height=700, device_scale_factor=2, mobile=False
    )


@pytest.mark.parametrize("frame", [False, True])
async def test_failed_setup_detaches_session_and_allows_retry(frame):
    setup = SimpleNamespace(apply=AsyncMock(side_effect=ValueError("setup failed")))
    options = Connect(endpoint="ws://localhost", session_setup=(setup,))
    browser, _ = _browser(options)
    attach = browser.tabs._frame_session if frame else browser.tabs._attach
    with pytest.raises(ValueError, match="setup failed"):
        await attach("target")
    assert not browser.tabs._sessions
    browser.client.target.detach_from_target.assert_awaited_once_with(
        session_id="session"
    )
    setup.apply.side_effect = None
    await attach("target")
    assert setup.apply.await_count == 2
    assert browser.client.target.attach_to_target.await_count == 2
    assert browser.tabs._sessions == {"session": "target"}


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
    tab = await browser.tabs._attach("tab")
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
            frame_id="frame",
            guid="id",
            url="https://example.org",
            suggested_filename="a.txt",
        ),
        None,
    )
    assert tab.dialog == ("confirm", "Sure?")
    opened = [event for event in events if isinstance(event, DialogOpenedEvent)]
    assert [(event.target_id, event.document_id) for event in opened] == [
        ("tab", "doc")
    ]
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
        browser.tabs._attach("popup", opened=True),
        browser.tabs._attach("popup", opened=True),
    )
    assert first is second
    browser.client.target.attach_to_target.assert_awaited_once()
    assert len([event for event in events if isinstance(event, TabOpenedEvent)]) == 1


async def test_close_forgets_sessions_and_ignores_stale_target_listing(monkeypatch):
    browser, events = _browser()
    closed = await browser.tabs._attach("closing")
    remaining = Tab(
        "remaining", SimpleNamespace(page=SimpleNamespace(bring_to_front=AsyncMock()))
    )
    browser.tabs._active = closed.id
    browser.client.target.get_targets.return_value = SimpleNamespace(
        target_infos=[
            SimpleNamespace(target_id=tid, type="page", title="", url="about:blank")
            for tid in ("closing", "remaining")
        ]
    )
    browser.tabs._tabs[remaining.id] = remaining
    gestures = []

    async def switch_tab(event, switch):
        gestures.append((event.gesture, event.target_id))
        await switch()

    monkeypatch.setattr(browser.tabs, "_change_tab", switch_tab)
    assert await browser.tabs.close(closed.id) is remaining
    assert gestures == [(TabGesture.CLOSE, "closing")]
    remaining.cdp.page.bring_to_front.assert_awaited_once_with()
    assert browser.active_tab is remaining
    assert closed.closed and closed.id not in browser.tabs._tabs
    assert "session" not in browser.tabs._sessions
    await browser.tabs._forget(closed.id)
    assert len([event for event in events if isinstance(event, TabClosedEvent)]) == 1


async def test_failed_startup_does_not_emit_disconnected():
    browser, events = _browser()
    await browser.aclose()
    assert not any(isinstance(event, DisconnectedEvent) for event in events)


async def test_frame_cache_is_action_scoped_and_invalidated_by_layout_and_document(
    monkeypatch,
):
    actions = ActionContext()
    browser, _ = _browser(actions=actions)
    tab = await browser.tabs._attach("tab")
    browser.client.target.get_targets.return_value = SimpleNamespace(target_infos=[])
    discover = AsyncMock(return_value=((), ()))
    monkeypatch.setattr(tabs_module, "discover_frames", discover)
    with actions.activate("action"):
        await tab.frames()
        await tab.frames()
        assert discover.await_count == 1
        tab.layout_changed()
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
    tab = await browser.tabs._attach("tab")
    frame = SimpleNamespace(
        id="frame", loader_id="new-document", url="https://example.org"
    )
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


class _RecordingSetup:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    async def apply(self, cdp, *, frame):
        assert cdp.page.enable.await_count > 0
        assert cdp.runtime.enable.await_count > 0
        assert cdp.page.set_lifecycle_events_enabled.await_count > 0
        metrics = cdp.emulation.set_device_metrics_override.await_count
        self.calls.append((self.name, cdp, frame, metrics))


def _browser(options=None, *, actions=None):
    events = []
    browser = ChromeBrowser(
        options or Connect(endpoint="ws://localhost/devtools/browser/test"),
        emit=AsyncMock(side_effect=events.append),
        current_action=str if actions is None else lambda: actions.action_id,
    )
    stack = AsyncExitStack()
    browser._stack = stack
    cdp = SimpleNamespace(
        page=SimpleNamespace(
            enable=AsyncMock(),
            set_lifecycle_events_enabled=AsyncMock(),
            get_frame_tree=AsyncMock(
                return_value=SimpleNamespace(
                    frame_tree=SimpleNamespace(
                        frame=SimpleNamespace(
                            id="frame", loader_id="doc", url="about:blank"
                        )
                    )
                )
            ),
        ),
        runtime=SimpleNamespace(enable=AsyncMock()),
        network=SimpleNamespace(enable=AsyncMock()),
        emulation=SimpleNamespace(set_device_metrics_override=AsyncMock()),
    )
    browser.client = SimpleNamespace(
        is_connected=True,
        session=Mock(return_value=cdp),
        target=SimpleNamespace(
            attach_to_target=AsyncMock(
                return_value=SimpleNamespace(session_id="session")
            ),
            detach_from_target=AsyncMock(),
            close_target=AsyncMock(),
            get_targets=AsyncMock(),
        ),
    )
    browser.tabs.client = browser.client
    browser.tabs._stack = stack
    return browser, events
