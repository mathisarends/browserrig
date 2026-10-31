import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browserrig.browser.base import BrowserEvents
from browserrig.browser.tab import Tab
from browserrig.events import WaitingEvent
from browserrig.tools import navigation as navigation_module
from browserrig.tools.navigation import NavigationTools


@pytest.mark.parametrize(
    "current, count, available", [(0, 1, False), (0, 3, True), (2, 3, False)]
)
async def test_forward_history_checks_bounds_and_only_dispatches_an_available_entry(
    current, count, available
):
    entries = [SimpleNamespace(id=10 + index) for index in range(count)]
    page = SimpleNamespace(
        get_navigation_history=AsyncMock(
            return_value=SimpleNamespace(current_index=current, entries=entries)
        ),
        navigate_to_history_entry=AsyncMock(),
    )
    tab = Tab("tab", SimpleNamespace(page=page))
    assert await tab.can_go_forward() is available
    assert await tab.go_forward() is available
    if available:
        page.navigate_to_history_entry.assert_awaited_once_with(
            entry_id=entries[current + 1].id
        )
    else:
        page.navigate_to_history_entry.assert_not_awaited()


async def test_wait_publishes_duration_and_tab_context_before_sleeping(monkeypatch):
    events = []
    browser = SimpleNamespace(
        action_lock=asyncio.Lock(),
        active_tab=SimpleNamespace(id="tab-1", document_id="doc-1"),
    )
    tools = SimpleNamespace(
        _browser=browser,
        _events=BrowserEvents("browser-1", AsyncMock(side_effect=events.append)),
    )

    async def sleep(seconds):
        assert seconds == 2 and browser.action_lock.locked()
        assert len(events) == 1 and isinstance(events[0], WaitingEvent)
        assert events[0].duration == seconds
        assert events[0].browser_id == "browser-1"
        assert events[0].target_id == "tab-1" and events[0].document_id == "doc-1"

    pause = AsyncMock(side_effect=sleep)
    monkeypatch.setattr(navigation_module.asyncio, "sleep", pause)
    assert (
        await NavigationTools.wait(tools, seconds=2)
        == "Wait completed; the next observation shows the current state."
    )
    pause.assert_awaited_once_with(2)
    assert not browser.action_lock.locked()
