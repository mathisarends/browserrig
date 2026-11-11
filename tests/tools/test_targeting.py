from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browserrig import Actions, Targeting
from browserrig.core import BrowserError, ElementPoint, StaleElement
from tests.fakes import FakeTab, mounted


async def test_hover_follows_one_target_move_and_preserves_reveal_receipt():
    async with mounted(Actions()) as (services, scope):
        first, moved = ElementPoint(x=10, y=20), ElementPoint(x=30, y=40)
        services.observe.element = AsyncMock(return_value=_handle(first, moved, moved))
        move = services.input.mouse.move_to = AsyncMock()
        result = await scope[Targeting].hover(
            ref="field", tab=services.browser.active_tab
        )
    assert result.scrolled and (result.x, result.y) == (30, 40)
    assert [(call.args[0].x, call.args[0].y) for call in move.await_args_list] == [
        (10, 20),
        (30, 40),
    ]


@pytest.mark.parametrize("change", ["document", "tab"])
async def test_hover_stops_when_its_document_or_focus_changes(change):
    async with mounted(Actions()) as (services, scope):
        tab = services.browser.active_tab
        services.observe.element = AsyncMock(
            return_value=_handle(ElementPoint(x=1, y=2))
        )

        async def change_target(_point):
            if change == "document":
                tab.document_id = "another-document"
            else:
                other = FakeTab()
                other.id = "another-tab"
                services.browser.active_tab = other

        move = services.input.mouse.move_to = AsyncMock(side_effect=change_target)
        with pytest.raises(StaleElement, match="changed during hover"):
            await scope[Targeting].hover(ref="field", tab=tab)
    move.assert_awaited_once()


async def test_hover_stops_after_a_bounded_number_of_target_moves():
    async with mounted(Actions()) as (services, scope):
        services.observe.element = AsyncMock(
            return_value=_handle(
                ElementPoint(x=1, y=2),
                ElementPoint(x=3, y=4),
                ElementPoint(x=5, y=6),
            )
        )
        move = services.input.mouse.move_to = AsyncMock()
        with pytest.raises(BrowserError, match="ELEMENT_MOVED"):
            await scope[Targeting].hover(ref="field", tab=services.browser.active_tab)
    assert move.await_count == 2


async def test_focus_change_during_document_sync_is_checked_before_moving():
    async with mounted(Actions()) as (services, scope):
        tab = services.browser.active_tab
        services.observe.element = AsyncMock(
            return_value=_handle(ElementPoint(x=1, y=2))
        )

        async def switch_focus():
            other = FakeTab()
            other.id = "another-tab"
            services.browser.active_tab = other

        tab.sync_document = AsyncMock(side_effect=switch_focus)
        move = services.input.mouse.move_to = AsyncMock()
        with pytest.raises(StaleElement, match="focused tab changed"):
            await scope[Targeting].hover(ref="field", tab=tab)
    move.assert_not_awaited()


def _handle(*points):
    return SimpleNamespace(
        element=SimpleNamespace(bounds=None),
        reveal=AsyncMock(return_value=True),
        locate=AsyncMock(side_effect=points),
    )
