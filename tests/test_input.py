import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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
    PointerPressedEvent,
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


async def test_initial_cursor_seeds_native_pointer_and_stream_without_origin_animation(monkeypatch):
    tab, events, commands = _tab()
    tab.document_id = "document-1"
    tab.cdp.page = SimpleNamespace(
        get_layout_metrics=AsyncMock(
            return_value=SimpleNamespace(
                css_layout_viewport=SimpleNamespace(client_width=1000, client_height=600)
            )
        )
    )
    sample = Mock(side_effect=[450, 330])
    monkeypatch.setattr("browserrig.input.mouse.random.uniform", sample)
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    await tab.mouse.initialize_cursor()
    assert tab.mouse.position == Point(x=450, y=330)
    assert len(commands) == 1 and commands[0]["type"] == "mouseMoved"
    assert (commands[0]["x"], commands[0]["y"]) == (450, 330)
    assert len(events) == 1 and isinstance(events[0], CursorStateEvent)
    assert (events[0].x, events[0].y) == (450, 330)
    assert events[0].target_id == tab.id and events[0].document_id == tab.document_id
    assert events[0].action_id == ""
    await tab.mouse.move_to(Point(x=800, y=500))
    movement_event = next(event for event in events if isinstance(event, CursorMovedEvent))
    assert movement_event.from_position == (450, 330)
    command_count = len(commands)
    await tab.mouse.initialize_cursor()
    assert sample.call_count == 2
    assert len(commands) == command_count
    assert isinstance(events[-1], CursorStateEvent)
    assert (events[-1].x, events[-1].y) == (800, 500)


async def test_mouse_and_keyboard_share_action_correlation_without_sharing_cursor_state(
    monkeypatch,
):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    tab, events, _ = _tab()
    assert tab.mouse is tab.input.mouse and tab.keyboard is tab.input.keyboard
    with tab.input.action("shared-action"):
        await tab.mouse.click(Point(x=120, y=80))
        await tab.keyboard.type_text("x")
    assert tab.mouse.position == Point(x=120, y=80)
    assert any(isinstance(event, PointerPressedEvent) for event in events)
    assert any(isinstance(event, KeyPressedEvent) for event in events)
    assert all(event.action_id == "shared-action" for event in events)
    assert tab.input.action_id == ""


async def test_exact_typing_emits_ordered_correlated_keys_without_persistable_text(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("browserrig.input.keyboard.asyncio.sleep", sleep)
    tab, events, commands = _tab()
    tab.document_id = "document-1"
    with tab.input.action("action-1"):
        await tab.keyboard.type_text("A+ä🙂\t")
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
    task = asyncio.create_task(tab.keyboard.press_key("a", hold_control=True, hold_shift=True))
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
    monkeypatch.setattr("browserrig.input.keyboard.asyncio.sleep", AsyncMock())
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
    task = asyncio.create_task(tab.mouse.move_to(Point(x=200, y=200)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(events[0], CursorMovedEvent)
    assert isinstance(events[-1], CursorStateEvent)
    assert (events[-1].x, events[-1].y) == (commands[-1]["x"], commands[-1]["y"])
    assert tab.mouse.position != Point(x=200, y=200)


@pytest.mark.parametrize("end", [Point(x=0, y=400), Point(x=400, y=0), Point(x=1, y=400)])
def test_cursor_paths_stay_in_viewport_at_edges(end):
    path = movement(Point(x=0, y=0), end)
    assert path.point(1) == end
    assert all(0 <= path.point(i / 60).x <= end.x for i in range(61))
    assert all(0 <= path.point(i / 60).y <= end.y for i in range(61))


async def test_cancelled_drag_releases_mouse_button():
    entered = asyncio.Event()

    async def dispatch(arguments):
        if arguments["type"] == "mouseMoved" and arguments.get("buttons") == 1:
            entered.set()
            await asyncio.Event().wait()

    tab, _, commands = _tab(dispatch=dispatch)
    task = asyncio.create_task(
        tab.mouse.drag(start=Point(x=10, y=10), end=Point(x=200, y=200), duration=1)
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["buttons"] == 0
