import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import ToolError
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
from browserrig.tools.keyboard import KeyboardTools


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


async def test_key_cancellation_releases_main_and_modifiers_and_hides_keyboard():
    entered = asyncio.Event()

    async def dispatch(command):
        if command.get("key") == "A" and command["type"] == "rawKeyDown":
            entered.set()
            await asyncio.Event().wait()

    tab, events, commands = _tab(dispatch=dispatch)
    task = asyncio.create_task(tab.input.press_key("a", hold_control=True, hold_shift=True))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    released = [command["key"] for command in commands if command["type"] == "keyUp"]
    assert released == ["A", "Shift", "Control"]
    assert not any(isinstance(event, KeyPressedEvent) for event in events)
    assert isinstance(events[-1], KeyboardVisibilityEvent) and not events[-1].visible


async def test_shortcut_dispatches_modifiers_without_inserting_text():
    tab, events, commands = _tab()
    await tab.press_key("a", hold_control=True)
    assert [(command["type"], command["key"]) for command in commands] == [
        ("rawKeyDown", "Control"),
        ("rawKeyDown", "a"),
        ("keyUp", "a"),
        ("keyUp", "Control"),
    ]
    assert next(event for event in events if isinstance(event, KeyPressedEvent)).modifiers == (
        "Control",
    )


@pytest.mark.parametrize(
    "modifier,name,flag,key",
    [
        ("hold_control", "Control", 2, "a"),
        ("hold_shift", "Shift", 8, "A"),
        ("hold_alt", "Alt", 1, "a"),
        ("hold_meta", "Meta", 4, "a"),
    ],
)
async def test_modifier_flags_reach_cdp_and_key_events(modifier, name, flag, key):
    tab, events, commands = _tab()
    await tab.press_key("a", **{modifier: True})
    down = [command for command in commands if command["type"] == "rawKeyDown"]
    assert [command["key"] for command in down] == [name, key]
    assert down[-1]["modifiers"] == flag
    event = next(event for event in events if isinstance(event, KeyPressedEvent))
    assert event.key == key and event.modifiers == (name,)
    assert commands[-1]["type"] == "keyUp" and commands[-1]["key"] == name


@pytest.mark.parametrize(
    "arguments", [{}, {"text": "hello", "key": "Enter"}, {"text": "hello", "hold_control": True}]
)
async def test_send_keys_rejects_ambiguous_arguments_before_dispatch(arguments):
    actions = SimpleNamespace(run=AsyncMock())
    with pytest.raises(ToolError):
        await KeyboardTools().send_keys(**arguments, actions=actions)
    actions.run.assert_not_awaited()


async def test_send_keys_distinguishes_literal_text_from_named_keys(monkeypatch):
    monkeypatch.setattr("browserrig.input.controller.asyncio.sleep", AsyncMock())
    tab, events, commands = _tab()

    async def run(*, kind, operation):
        assert kind in {"type", "press"}
        return (await operation(tab)).text

    actions = SimpleNamespace(run=run)
    await KeyboardTools().send_keys(text="Escape", actions=actions)
    assert [command["text"] for command in commands if command["type"] == "char"] == list("Escape")
    commands.clear()
    events.clear()
    await KeyboardTools().send_keys(key="Escape", actions=actions)
    assert [command["type"] for command in commands] == ["rawKeyDown", "keyUp"]
    assert [event.key for event in events if isinstance(event, KeyPressedEvent)] == ["Escape"]


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
