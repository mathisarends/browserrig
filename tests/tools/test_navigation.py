from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browserrig.browser import Tab
from browserrig.tools import Actions, NavigationTools
from browserrig.tools import navigation as navigation_module
from browserrig.tools.intents import WaitIntent
from tests.fakes import mounted


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
    assert await tab.can_go_back() is (current > 0)
    assert await tab.can_go_forward() is available
    assert await tab.go_forward() is available
    if available:
        page.navigate_to_history_entry.assert_awaited_once_with(
            entry_id=entries[current + 1].id
        )
    else:
        page.navigate_to_history_entry.assert_not_awaited()


async def test_wait_stages_its_pause_under_exclusive_control(monkeypatch):
    staged = []

    async def stage(intent, staged_tab, step):
        staged.append((intent, staged_tab))
        await step()

    async def sleep(seconds):
        assert seconds == 2 and coordination.busy

    pause = AsyncMock(side_effect=sleep)
    monkeypatch.setattr(navigation_module.asyncio, "sleep", pause)
    async with mounted(Actions(), _NavigationTools()) as (services, scope):
        coordination = services.coordination
        tab = services.browser.active_tab
        scope[Actions].stage = stage
        assert (
            await scope[_NavigationTools].wait(seconds=2)
            == "Wait completed; the next observation shows the current state."
        )
    assert staged == [(WaitIntent(2), tab)]
    pause.assert_awaited_once_with(2)
    assert not coordination.busy


class _NavigationTools(NavigationTools, provides=True):
    """Expose the mounted tool for direct-call coverage."""
