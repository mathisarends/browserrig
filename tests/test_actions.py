# Internal transaction state is inspected to verify failure receipts.
# pylint: disable=protected-access

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import ToolError

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.events import ActionFailedEvent
from browserrig.kinds import ActionKind
from browserrig.tools.execution import Actions


@pytest.mark.parametrize(
    "error", [BrowserError("wrong input"), ToolError("denied"), ValueError("bad")]
)
async def test_action_keeps_error_details_and_uncertain_dispatch(error):
    actions, events = _actions()
    with pytest.raises(ToolError, match=str(error)) as caught:
        await Actions.run(actions, kind=ActionKind.TYPE, operation=AsyncMock(side_effect=error))
    assert "may have run" in str(caught.value)
    receipt = next(event for event in events if isinstance(event, ActionFailedEvent))
    assert receipt.dispatched and str(error) in receipt.reason


async def test_validation_rejects_before_dispatch():
    actions, events = _actions()
    operation = AsyncMock()
    with pytest.raises(ToolError, match="wrong input") as caught:
        await Actions.run(
            actions,
            kind=ActionKind.UPLOAD,
            check=AsyncMock(side_effect=BrowserError("wrong input")),
            operation=operation,
        )
    assert "may have run" not in str(caught.value)
    operation.assert_not_awaited()
    assert len(events) == 1
    assert isinstance(events[0], ActionFailedEvent) and not events[0].dispatched


@pytest.mark.parametrize(
    "kind",
    [
        ActionKind.TAB,
        ActionKind.OPEN_TAB,
        ActionKind.SWITCH_TAB,
        ActionKind.CLOSE_TAB,
        ActionKind.OPEN_FILE,
        ActionKind.OPEN_DOWNLOADED_FILE,
    ],
)
async def test_tab_management_does_not_wait_on_current_page_dialog(kind):
    tab = SimpleNamespace(url="about:blank", document_id="doc", dialog=("alert", "hello"))
    before = await Actions._prepare(SimpleNamespace(), tab, kind)
    assert before.url == tab.url and before.document_id == tab.document_id


async def test_global_keyboard_input_rejects_a_document_changed_between_calls():
    tab = SimpleNamespace(
        id="tab",
        document_id="new-doc",
        sync_document=AsyncMock(),
    )
    actions = SimpleNamespace(
        observe=SimpleNamespace(
            snapshot=SimpleNamespace(
                tab_id="tab",
                document_id="old-doc",
            )
        )
    )
    with pytest.raises(BrowserError, match="observe before input"):
        await Actions._prepare(actions, tab, ActionKind.PRESS)


def _actions():
    events = []
    tab = Tab("tab", SimpleNamespace())
    actions = SimpleNamespace(
        browser=SimpleNamespace(action_lock=asyncio.Lock(), active_tab=tab),
        _events=SimpleNamespace(emit=AsyncMock(side_effect=events.append)),
        _prepare=AsyncMock(return_value=SimpleNamespace()),
    )
    actions._fail = lambda *args: Actions._fail(actions, *args)
    return actions, events
