import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed.events import EventRegistry

from browserrig.browser.models import Point
from browserrig.browser.tab import Tab
from browserrig.events import (
    INPUT_EVENTS,
    CursorMovedEvent,
    CursorStateEvent,
    KeyboardVisibilityEvent,
    KeyPressedEvent,
)
from browserrig.input.pointer import movement


def _tab(*, dispatch=None):
    events, commands = [], []

    async def emit(event):
        EventRegistry(INPUT_EVENTS).validate(event)
        events.append(event)

    async def send(**arguments):
        commands.append(arguments)
        if dispatch is not None:
            await dispatch(arguments)

    cdp = SimpleNamespace(
        input=SimpleNamespace(dispatch_key_event=send, insert_text=send, dispatch_mouse_event=send)
    )
    return Tab("tab-1", cdp, emit=emit), events, commands


async def test_exact_typing_emits_ordered_correlated_keys_without_persistable_text(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("browserrig.input.controller.asyncio.sleep", sleep)
    tab, events, commands = _tab()
    tab.document_id = "document-1"
    with tab.input.action("action-1"):
        await tab.input.type_text("A+ä🙂\t")
    assert [command["text"] for command in commands if command["type"] == "char"] == list("A+ä🙂\t")
    keys = [event for event in events if isinstance(event, KeyPressedEvent)]
    assert [event.key for event in keys] == list("A+ä🙂\t")
    assert all(event.duration == 0.05 for event in keys)
    assert all(event.target_id == "tab-1" and event.document_id == "document-1" for event in events)
    assert all(event.action_id == "action-1" for event in events)
    assert tab.input.action_id == ""
    assert sleep.await_count == len(keys)
    assert all(call.args == (0.05,) for call in sleep.await_args_list)
    assert isinstance(events[0], KeyboardVisibilityEvent) and events[0].visible
    assert isinstance(events[-1], KeyboardVisibilityEvent) and not events[-1].visible


async def test_sensitive_typing_does_not_reveal_characters_or_shift(monkeypatch):
    monkeypatch.setattr("browserrig.input.controller.asyncio.sleep", AsyncMock())
    tab, events, _ = _tab()
    await tab.input.type_text("Secret!", sensitive=True)
    keys = [event for event in events if isinstance(event, KeyPressedEvent)]
    assert len(keys) == 7
    assert all(event.key == "" and event.modifiers == () and event.sensitive for event in keys)


async def test_key_cancellation_releases_main_and_modifiers_and_hides_keyboard():
    entered = asyncio.Event()

    async def dispatch(command):
        if command.get("key") == "a" and command["type"] == "rawKeyDown":
            entered.set()
            await asyncio.Event().wait()

    tab, events, commands = _tab(dispatch=dispatch)
    task = asyncio.create_task(tab.input.press_key("Control+Shift+a"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    released = [command["key"] for command in commands if command["type"] == "keyUp"]
    assert released == ["a", "Shift", "Control"]
    assert not any(isinstance(event, KeyPressedEvent) for event in events)
    assert isinstance(events[-1], KeyboardVisibilityEvent) and not events[-1].visible


async def test_shortcut_dispatches_modifiers_without_inserting_text():
    tab, events, commands = _tab()
    await tab.press_key("Control+a")
    assert [(command["type"], command["key"]) for command in commands] == [
        ("rawKeyDown", "Control"),
        ("rawKeyDown", "a"),
        ("keyUp", "a"),
        ("keyUp", "Control"),
    ]
    assert next(event for event in events if isinstance(event, KeyPressedEvent)).modifiers == (
        "Control",
    )


async def test_cancelled_cursor_reports_actual_position():
    tab, events, commands = _tab()
    task = asyncio.create_task(tab.input.move_to(Point(x=200, y=200)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(events[0], CursorMovedEvent)
    assert isinstance(events[-1], CursorStateEvent)
    assert (events[-1].x, events[-1].y) == (commands[-1]["x"], commands[-1]["y"])
    assert tab.input.position != Point(x=200, y=200)


@pytest.mark.parametrize("end", [Point(x=0, y=400), Point(x=400, y=0), Point(x=1, y=400)])
def test_cursor_paths_stay_in_viewport_at_edges(end):
    path = movement(Point(x=0, y=0), end)
    assert path.point(1) == end
    assert all(0 <= path.point(i / 60).x <= end.x for i in range(61))
    assert all(0 <= path.point(i / 60).y <= end.y for i in range(61))
