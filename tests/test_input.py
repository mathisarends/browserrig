# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

import asyncio
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from harnessed import ToolError
from harnessed.events import EventRegistry

from browserrig.browser.tab import Tab
from browserrig.core.errors import BrowserError
from browserrig.core.geometry import Point
from browserrig.events import (
    INPUT_EVENTS,
    CursorEnteredEvent,
    CursorMovedEvent,
    CursorStateEvent,
    CursorStyleEvent,
    FileTransferEvent,
    KeyboardVisibilityEvent,
    KeyPressedEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    ScrolledEvent,
    TabPressedEvent,
)
from browserrig.input import Input
from browserrig.input.pointer import movement
from browserrig.input.wheel import wheel_duration, wheel_progress
from browserrig.kinds import CursorStyle, FileTransferDirection, TabGesture
from browserrig.tools.keyboard import KeyboardTools


async def test_mouse_and_keyboard_share_action_correlation_without_sharing_cursor_state(
    monkeypatch,
):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    devices, _tab, events, _ = _rig()
    with devices.action("shared-action"):
        await devices.mouse.click(Point(x=120, y=80))
        await devices.keyboard.type_text("x")
    assert devices.mouse.position == Point(x=120, y=80)
    assert any(isinstance(event, PointerPressedEvent) for event in events)
    assert any(isinstance(event, KeyPressedEvent) for event in events)
    assert all(event.action_id == "shared-action" for event in events)
    assert devices._action_id == ""


@pytest.mark.parametrize("button,mask", [("left", 1), ("right", 2)])
@pytest.mark.parametrize("count", [1, 2])
async def test_click_dispatches_selected_button_and_click_count(monkeypatch, button, mask, count):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    devices, _tab, events, commands = _rig()
    await devices.mouse.click(Point(x=120, y=80), button=button, count=count)
    clicks = [command for command in commands if command["type"] != "mouseMoved"]
    assert [(c["type"], c["buttons"], c["click_count"]) for c in clicks] == [
        item
        for index in range(1, count + 1)
        for item in [("mousePressed", mask, index), ("mouseReleased", 0, index)]
    ]
    assert all(command["button"] == button for command in clicks)
    receipts = [e for e in events if isinstance(e, (PointerPressedEvent, PointerReleasedEvent))]
    assert len(receipts) == count * 2 and all(e.button == button for e in receipts)


async def test_cancelled_right_click_releases_the_right_button(monkeypatch):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())

    async def cancel(arguments):
        if arguments["type"] == "mousePressed":
            raise asyncio.CancelledError

    devices, _tab, _, commands = _rig(dispatch=cancel)
    with pytest.raises(asyncio.CancelledError):
        await devices.mouse.click(Point(x=120, y=80), button="right")
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["button"] == "right" and commands[-1]["buttons"] == 0


async def test_exact_typing_emits_ordered_correlated_keys_without_persistable_text(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("browserrig.input.keyboard.asyncio.sleep", sleep)
    devices, tab, events, commands = _rig()
    tab.document_id = "document-1"
    with devices.action("action-1"):
        await devices.keyboard.type_text("A+ä🙂\t")
    assert [command["text"] for command in commands if command["type"] == "char"] == list("A+ä🙂\t")
    keys = [event for event in events if isinstance(event, KeyPressedEvent)]
    assert [event.key for event in keys] == list("A+ä🙂\t")
    assert all(event.duration == 0.05 for event in keys)
    assert all(event.target_id == "tab-1" and event.document_id == "document-1" for event in events)
    assert all(event.action_id == "action-1" for event in events)
    assert devices._action_id == ""
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

    devices, _tab, events, commands = _rig(dispatch=dispatch)
    task = asyncio.create_task(devices.keyboard.press_key("a", hold_control=True, hold_shift=True))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    released = [command["key"] for command in commands if command["type"] == "keyUp"]
    assert released == ["A", "Shift", "Control"]
    assert not any(isinstance(event, KeyPressedEvent) for event in events)
    assert isinstance(events[-1], KeyboardVisibilityEvent) and not events[-1].visible


async def test_shortcut_dispatches_modifiers_without_inserting_text():
    devices, _tab, events, commands = _rig()
    await devices.keyboard.press_key("a", hold_control=True)
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
    devices, _tab, events, commands = _rig()
    await devices.keyboard.press_key("a", **{modifier: True})
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
    devices, tab, events, commands = _rig()

    async def run(*, kind, operation):
        assert kind in {"type", "press"}
        return (await operation(tab)).text

    actions = SimpleNamespace(run=run)
    tools = SimpleNamespace(_browser=SimpleNamespace(keyboard=devices.keyboard))
    await KeyboardTools.send_keys(tools, text="Escape", actions=actions)
    assert [command["text"] for command in commands if command["type"] == "char"] == list("Escape")
    commands.clear()
    events.clear()
    await KeyboardTools.send_keys(tools, key="Escape", actions=actions)
    assert [command["type"] for command in commands] == ["rawKeyDown", "keyUp"]
    assert [event.key for event in events if isinstance(event, KeyPressedEvent)] == ["Escape"]


async def test_cancelled_cursor_reports_actual_position():
    devices, _tab, events, commands = _rig()
    task = asyncio.create_task(devices.mouse.move_to(Point(x=200, y=200)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(events[0], CursorMovedEvent)
    assert isinstance(events[-1], CursorStateEvent)
    assert (events[-1].x, events[-1].y) == (commands[-1]["x"], commands[-1]["y"])
    assert devices.mouse.position != Point(x=200, y=200)


async def test_cursor_style_is_reported_only_when_it_changes(monkeypatch):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    devices, tab, events, _ = _rig()
    styles = iter([CursorStyle.POINTER, CursorStyle.POINTER, None, CursorStyle.TEXT])
    probe = AsyncMock(side_effect=lambda point: next(styles))
    tab.cursor_style = probe
    for x in (10, 20, 30, 40):
        await devices.mouse.move_to(Point(x=x, y=10))
    reported = [event.style for event in events if isinstance(event, CursorStyleEvent)]
    assert reported == [CursorStyle.POINTER, CursorStyle.TEXT]
    assert probe.await_args_list[-1].args == (Point(x=40, y=10),)
    events.clear()
    await devices.mouse.publish_cursor()
    assert [type(event) for event in events] == [CursorStateEvent, CursorStyleEvent]
    assert events[-1].style == CursorStyle.TEXT


@pytest.mark.parametrize(
    "value,style",
    [
        ("pointer", CursorStyle.POINTER),
        ("url(hand.png) 4 4, Pointer", CursorStyle.POINTER),
        ("url(custom.cur)", CursorStyle.DEFAULT),
        ("-webkit-grab", CursorStyle.DEFAULT),
    ],
)
def test_cursor_style_parse_keeps_the_keyword_fallback(value, style):
    assert CursorStyle.parse(value) is style


async def test_file_transfer_is_correlated_and_holds_for_its_animation(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("browserrig.input.controller.asyncio.sleep", sleep)
    devices, _tab, events, _ = _rig()
    with devices.action("upload-1"):
        await devices.transfer(FileTransferDirection.UPLOAD, ("a.pdf", "b.png"), Point(x=12, y=34))
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, FileTransferEvent)
    assert event.paths == ("a.pdf", "b.png") and (event.x, event.y) == (12, 34)
    assert event.action_id == "upload-1" and event.target_id == "tab-1"
    sleep.assert_awaited_once_with(event.duration)


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

    devices, tab, _, commands = _rig(dispatch=dispatch)
    task = asyncio.create_task(
        devices.mouse.drag(start=Point(x=10, y=10), end=Point(x=200, y=200), duration=1)
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["buttons"] == 0
    tab.cdp.input.cancel_dragging.assert_awaited_once_with()


async def test_failed_native_drag_cancellation_still_releases_mouse_button():
    async def dispatch(arguments):
        if arguments["type"] == "mouseMoved" and arguments.get("buttons") == 1:
            raise RuntimeError("movement failed")

    devices, tab, _, commands = _rig(dispatch=dispatch)
    tab.cdp.input.cancel_dragging.side_effect = RuntimeError("cancel failed")
    with pytest.raises(RuntimeError, match="cancel failed"):
        await devices.mouse.drag(start=Point(x=10, y=10), end=Point(x=200, y=200), duration=0.1)
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["buttons"] == 0


def _rest(devices, tab, point):
    rest = devices.mouse._rest(tab)
    rest.position, rest.placed = point, True


def _rig(*, dispatch=None):
    tab, events, commands = _tab(dispatch=dispatch)
    return Input(lambda: tab), tab, events, commands


def _tab(target_id="tab-1", *, dispatch=None, events=None, viewport=(1000, 600)):
    events = [] if events is None else events
    commands = []

    async def emit(event):
        EventRegistry(INPUT_EVENTS).validate(event)
        events.append(event)

    async def send(**arguments):
        commands.append(arguments)
        if dispatch is not None:
            await dispatch(arguments)

    width, height = viewport
    cdp = SimpleNamespace(
        input=SimpleNamespace(
            dispatch_key_event=send,
            insert_text=send,
            dispatch_mouse_event=send,
            cancel_dragging=AsyncMock(),
        ),
        page=SimpleNamespace(
            get_layout_metrics=AsyncMock(
                return_value=SimpleNamespace(
                    css_layout_viewport=SimpleNamespace(client_width=width, client_height=height)
                )
            )
        ),
    )
    return Tab(target_id, cdp, emit=emit), events, commands


async def test_first_tab_seeds_the_pointer_without_a_tab_press(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", sleep)
    monkeypatch.setattr("browserrig.input.mouse.random.uniform", Mock(side_effect=[450, 330]))
    tab, events, commands = _tab()
    focus: dict[str, Tab | None] = {"tab": None}
    devices = Input(lambda: focus["tab"])

    async def switch():
        focus["tab"] = tab

    await devices.mouse.switch_tab(TabGesture.ACTIVATE, tab.id, switch)
    assert devices.mouse.position_in(tab.id) == Point(x=450, y=330)
    assert [(c["type"], c["x"], c["y"]) for c in commands] == [("mouseMoved", 450, 330)]
    assert [type(event) for event in events] == [CursorStateEvent]
    assert (events[0].x, events[0].y) == (450, 330) and events[0].target_id == tab.id
    sleep.assert_not_awaited()


async def test_tab_switch_presses_the_tab_then_enters_the_new_page(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", sleep)
    monkeypatch.setattr("browserrig.input.mouse.random.uniform", Mock(side_effect=[500, 300]))
    events = []
    first, _, first_commands = _tab("first", events=events)
    second, _, second_commands = _tab("second", events=events)
    focus = {"tab": first}
    devices = Input(lambda: focus["tab"])
    _rest(devices, first, Point(x=100, y=80))

    async def switch():
        events.append("switched")
        focus["tab"] = second

    with devices.action("switch-1"):
        await devices.mouse.switch_tab(TabGesture.ACTIVATE, "second", switch)
    assert len(events) == 4
    pressed, switched, entered, landed = events[0], events[1], events[2], events[3]
    assert isinstance(pressed, TabPressedEvent) and pressed.target_id == "first"
    assert pressed.gesture is TabGesture.ACTIVATE and pressed.tab_id == "second"
    assert pressed.from_position == (100, 80)
    assert switched == "switched"
    assert isinstance(entered, CursorEnteredEvent) and entered.target_id == "second"
    assert entered.to_position == (500, 300)
    assert isinstance(landed, CursorStateEvent) and (landed.x, landed.y) == (500, 300)
    assert all(event.action_id == "switch-1" for event in (pressed, entered, landed))
    assert [call.args for call in sleep.await_args_list] == [
        (pressed.duration,),
        (entered.duration,),
    ]
    # Hover in the new page is real: the renderer gets the landing position too.
    assert not first_commands
    assert [(c["type"], c["x"], c["y"]) for c in second_commands] == [("mouseMoved", 500, 300)]


async def test_returning_to_a_tab_lands_where_its_pointer_rested(monkeypatch):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    sample = Mock()
    monkeypatch.setattr("browserrig.input.mouse.random.uniform", sample)
    events = []
    first, _, first_commands = _tab("first", events=events)
    second, _, _ = _tab("second", events=events)
    focus = {"tab": second}
    devices = Input(lambda: focus["tab"])
    _rest(devices, first, Point(x=100, y=80))
    _rest(devices, second, Point(x=700, y=400))

    async def switch():
        focus["tab"] = first

    await devices.mouse.switch_tab(TabGesture.CLOSE, "second", switch)
    sample.assert_not_called()
    pressed = next(event for event in events if isinstance(event, TabPressedEvent))
    assert pressed.gesture is TabGesture.CLOSE and pressed.from_position == (700, 400)
    entered = next(event for event in events if isinstance(event, CursorEnteredEvent))
    assert entered.to_position == (100, 80)
    assert [(c["x"], c["y"]) for c in first_commands] == [(100, 80)]


async def test_a_gesture_stays_on_the_tab_where_it_started(monkeypatch):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    second, _, second_commands = _tab("second")
    focus = {}

    async def dispatch(arguments):
        if arguments.get("buttons") == 1:
            focus["tab"] = second

    first, _, first_commands = _tab("first", dispatch=dispatch)
    focus["tab"] = first
    devices = Input(lambda: focus["tab"])
    await devices.mouse.drag(start=Point(x=10, y=10), end=Point(x=200, y=200), duration=0.1)
    assert first_commands[-1]["type"] == "mouseReleased"
    assert not second_commands
    assert devices.mouse.position_in(first.id) == Point(x=200, y=200)
    assert devices.mouse.position_in(second.id) is None


async def test_input_without_a_focused_tab_is_rejected():
    devices = Input(lambda: None)
    with pytest.raises(BrowserError, match="No active tab"):
        await devices.mouse.move_to(Point(x=1, y=1))
    with pytest.raises(BrowserError, match="No active tab"):
        await devices.keyboard.press_key("a")


def test_wheel_timing_follows_chrome_smooth_scroll():
    # Chrome's scrollBy({behavior: 'smooth'}) takes about sqrt(distance) frames at 60 Hz.
    assert wheel_duration(600) == pytest.approx(0.408, abs=0.001)
    assert wheel_duration(10) == 0.15 and wheel_duration(50_000) == 1.5
    # Progress Chrome reached at 10/25/50/75% of a smooth scroll's duration.
    assert wheel_progress(0) == 0 and wheel_progress(1) == 1
    measured = {0.1: 0.03, 0.25: 0.40, 0.5: 0.85, 0.75: 0.97}
    for fraction, progress in measured.items():
        assert wheel_progress(fraction) == pytest.approx(progress, abs=0.02)


async def test_scroll_spreads_wheel_input_over_frames_along_the_curve(monkeypatch):
    monkeypatch.setattr("browserrig.input.mouse.asyncio.sleep", AsyncMock())
    devices, _tab, events, commands = _rig()
    await devices.mouse.scroll(delta_y=600, delta_x=-60)
    wheels = [c for c in commands if c["type"] == "mouseWheel"]
    assert len(wheels) == 25
    assert sum(c["delta_y"] for c in wheels) == pytest.approx(600)
    assert sum(c["delta_x"] for c in wheels) == pytest.approx(-60)
    steps = [c["delta_y"] for c in wheels]
    assert all(step > 0 for step in steps)
    # The largest steps come early, and the scroll settles in small ones.
    assert steps.index(max(steps)) < len(steps) // 3 and steps[-1] < 5
    scrolled = [event for event in events if isinstance(event, ScrolledEvent)]
    assert [(e.delta_x, e.delta_y) for e in scrolled] == [(-60, 600)]
    assert scrolled[0].duration == wheel_duration(math.hypot(600, 60))
