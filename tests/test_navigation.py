from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browserrig.browser.tab import Tab


@pytest.mark.parametrize("current, count, available", [(0, 1, False), (0, 3, True), (2, 3, False)])
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
        page.navigate_to_history_entry.assert_awaited_once_with(entry_id=entries[current + 1].id)
    else:
        page.navigate_to_history_entry.assert_not_awaited()
