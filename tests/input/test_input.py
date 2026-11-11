# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

import asyncio
import math
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import ToolError
from harnessed.events import EventRegistry
from harnessed.plugins import Service
from harnessed.testing import mount_plugin

from browserrig.browser import Tab
from browserrig.choreography import (
    SCENE_EVENTS,
    BarTypedEvent,
    CursorEnteredEvent,
    Stage,
    TabPressedEvent,
    scenes,
)
from browserrig.choreography.scenes import Scene
from browserrig.core import BrowserError, Point
from browserrig.events import (
    INPUT_EVENTS,
    CursorMovedEvent,
    CursorStateEvent,
    CursorStyleEvent,
    KeyboardVisibilityEvent,
    KeyPressedEvent,
    PointerPressedEvent,
    PointerReleasedEvent,
    ScrolledEvent,
)
from browserrig.input import (
    CENTER,
    CursorPath,
    HumanMotor,
    Input,
    Instant,
    KeyStroke,
    Unseen,
)
from browserrig.input import keyboard as keyboard_module
from browserrig.input import mouse as mouse_module
from browserrig.input.pointer import movement
from browserrig.input.wheel import wheel_duration, wheel_progress
from browserrig.kinds import BrowserBar, CursorStyle, TabGesture
from browserrig.tools import Actions, KeyboardTools, NavigateIntent
from tests.fakes import FakeServices


async def test_mouse_and_keyboard_share_action_correlation_without_sharing_cursor_state(
    monkeypatch,
):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
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
async def test_click_dispatches_selected_button_and_click_count(
    monkeypatch, button, mask, count
):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
    devices, _tab, events, commands = _rig()
    await devices.mouse.click(Point(x=120, y=80), button=button, count=count)
    clicks = [command for command in commands if command["type"] != "mouseMoved"]
    assert [(c["type"], c["buttons"], c["click_count"]) for c in clicks] == [
        item
        for index in range(1, count + 1)
        for item in [("mousePressed", mask, index), ("mouseReleased", 0, index)]
    ]
    assert all(command["button"] == button for command in clicks)
    receipts = [
        e for e in events if isinstance(e, (PointerPressedEvent, PointerReleasedEvent))
    ]
    assert len(receipts) == count * 2 and all(e.button == button for e in receipts)


async def test_held_modifier_wraps_the_click_and_shows_on_the_keyboard(monkeypatch):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
    devices, _tab, events, commands = _rig()
    async with devices.keyboard.hold("Control") as modifiers:
        await devices.mouse.click(Point(x=120, y=80), modifiers=modifiers)
    sent = [
        (command["type"], command.get("key"), command.get("modifiers"))
        for command in commands
        if command["type"] != "mouseMoved"
    ]
    assert sent == [
        ("rawKeyDown", "Control", 2),
        ("mousePressed", None, 2),
        ("mouseReleased", None, 2),
        ("keyUp", "Control", 0),
    ]
    shown = [
        e for e in events if isinstance(e, (KeyboardVisibilityEvent, KeyPressedEvent))
    ]
    assert [type(e) for e in shown] == [
        KeyboardVisibilityEvent,
        KeyPressedEvent,
        KeyboardVisibilityEvent,
    ]
    assert shown[1].key == "Control" and not shown[2].visible
    with pytest.raises(BrowserError):
        async with devices.keyboard.hold("Enter"):
            pass


async def test_cancelled_right_click_releases_the_right_button(monkeypatch):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())

    async def cancel(arguments):
        if arguments["type"] == "mousePressed":
            raise asyncio.CancelledError

    devices, _tab, _, commands = _rig(dispatch=cancel)
    with pytest.raises(asyncio.CancelledError):
        await devices.mouse.click(Point(x=120, y=80), button="right")
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["button"] == "right" and commands[-1]["buttons"] == 0


async def test_exact_typing_emits_ordered_correlated_keys_without_persistable_text(
    monkeypatch,
):
    sleep = AsyncMock()
    monkeypatch.setattr(keyboard_module.asyncio, "sleep", sleep)
    devices, tab, events, commands = _rig()
    tab.document_id = "document-1"
    with devices.action("action-1"):
        await devices.keyboard.type_text("A+ä🙂\t")
    assert [
        command["text"] for command in commands if command["type"] == "char"
    ] == list("A+ä🙂\t")
    keys = [event for event in events if isinstance(event, KeyPressedEvent)]
    assert [event.key for event in keys] == list("A+ä🙂\t")
    assert all(event.duration == 0.05 for event in keys)
    assert all(
        event.target_id == "tab-1" and event.document_id == "document-1"
        for event in events
    )
    assert all(event.action_id == "action-1" for event in events)
    assert devices._action_id == ""
    assert sleep.await_count == len(keys)
    assert all(call.args == (0.05,) for call in sleep.await_args_list)
    assert isinstance(events[0], KeyboardVisibilityEvent) and events[0].visible
    assert isinstance(events[-1], KeyboardVisibilityEvent) and not events[-1].visible


async def test_address_typing_shows_each_key_without_page_input_and_submits(
    monkeypatch,
):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    _devices, tab, events, commands = _rig()
    loaded = AsyncMock(return_value="loaded")

    result = await scenes.navigate(
        Scene(tab, "action-1"), NavigateIntent(url="https://a.b/", typed="ab c"), loaded
    )

    assert result == "loaded"
    assert not commands
    typed = [event for event in events if isinstance(event, BarTypedEvent)]
    assert [(event.key, event.text) for event in typed] == [
        ("a", "a"),
        ("b", "ab"),
        (" ", "ab "),
        ("c", "ab c"),
        ("Enter", "ab c"),
    ]
    assert all(event.browser_bar == BrowserBar.ADDRESS for event in typed)
    assert all(event.action_id == "action-1" for event in events)
    assert all(event.duration == 0.05 for event in typed)
    assert isinstance(events[0], KeyboardVisibilityEvent) and events[0].visible
    assert isinstance(events[-1], KeyboardVisibilityEvent) and not events[-1].visible


async def test_long_addresses_type_faster_and_submit_with_enter(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    _devices, tab, events, _ = _rig()
    address = "example.org/" + "x" * 68
    intent = NavigateIntent(url=f"https://{address}", typed=address)
    await scenes.navigate(Scene(tab, ""), intent, AsyncMock())
    typed = [event for event in events if isinstance(event, BarTypedEvent)]
    assert len(typed) == len(address) + 1
    assert (typed[-1].key, typed[-1].text) == ("Enter", address)
    # The whole address stays within the bar's time budget, Enter included.
    assert all(event.duration == pytest.approx(0.8 / len(address)) for event in typed)
    assert (
        sum(call.args[0] for call in sleep.await_args_list) <= 0.8 + typed[0].duration
    )


async def test_key_cancellation_releases_main_and_modifiers_and_hides_keyboard():
    entered = asyncio.Event()

    async def dispatch(command):
        if command.get("key") == "A" and command["type"] == "rawKeyDown":
            entered.set()
            await asyncio.Event().wait()

    devices, _tab, events, commands = _rig(dispatch=dispatch)
    task = asyncio.create_task(
        devices.keyboard.press_key("a", hold_control=True, hold_shift=True)
    )
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
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
    assert next(
        event for event in events if isinstance(event, KeyPressedEvent)
    ).modifiers == ("Control",)


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
    "arguments",
    [{}, {"text": "hello", "key": "Enter"}, {"text": "hello", "hold_control": True}],
)
async def test_send_keys_rejects_ambiguous_arguments_before_dispatch(arguments):
    actions = SimpleNamespace(run=AsyncMock())
    async with mount_plugin(
        KeyboardTools(), services=[FakeServices(), Service(Actions, actions)]
    ) as tools:
        with pytest.raises(ToolError):
            await tools.send_keys(**arguments)
    actions.run.assert_not_awaited()


async def test_send_keys_distinguishes_literal_text_from_named_keys(monkeypatch):
    monkeypatch.setattr(keyboard_module.asyncio, "sleep", AsyncMock())
    devices, _tab, events, commands = _rig()
    tools = SimpleNamespace(
        _browser=SimpleNamespace(input=devices),
        _secrets=None,
        _actions=_DirectActions(),
    )
    await KeyboardTools.send_keys(tools, text="Escape")
    assert [
        command["text"] for command in commands if command["type"] == "char"
    ] == list("Escape")
    commands.clear()
    events.clear()
    await KeyboardTools.send_keys(tools, key="Escape")
    assert [command["type"] for command in commands] == ["rawKeyDown", "keyUp"]
    assert [event.key for event in events if isinstance(event, KeyPressedEvent)] == [
        "Escape"
    ]


async def test_cancelled_cursor_reports_actual_position():
    devices, _tab, events, commands = _rig()
    task = asyncio.create_task(devices.mouse.move_to(Point(x=200, y=200)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert isinstance(events[0], CursorMovedEvent)
    assert isinstance(events[-1], CursorStateEvent)
    assert (events[-1].x, events[-1].y) == (commands[-1]["x"], commands[-1]["y"])
    assert devices.mouse.position != Point(x=200, y=200)


async def test_cursor_style_is_reported_only_when_it_changes(monkeypatch):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
    devices, tab, events, _ = _rig()
    styles = iter([CursorStyle.POINTER, CursorStyle.POINTER, None, CursorStyle.TEXT])
    probe = AsyncMock(side_effect=lambda point: next(styles))
    tab.input.cursor_style = probe
    for x in (10, 20, 30, 40):
        await devices.mouse.move_to(Point(x=x, y=10))
    reported = [event.style for event in events if isinstance(event, CursorStyleEvent)]
    assert reported == [CursorStyle.POINTER, CursorStyle.TEXT]
    assert probe.await_args_list[-1].args == (Point(x=40, y=10),)
    events.clear()
    await devices.mouse.publish_cursor()
    assert [type(event) for event in events] == [CursorStateEvent, CursorStyleEvent]
    assert events[-1].style == CursorStyle.TEXT


async def test_unwatched_pointer_never_asks_the_page_for_its_cursor():
    tab, events, _ = _tab()
    probe = AsyncMock(return_value=CursorStyle.POINTER)
    tab.input.cursor_style = probe
    devices = Input(lambda: tab.input)
    await devices.mouse.move_to(Point(x=10, y=10))
    probe.assert_not_awaited()
    assert not events


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


@pytest.mark.parametrize(
    "end", [Point(x=0, y=400), Point(x=400, y=0), Point(x=1, y=400)]
)
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
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
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
        await devices.mouse.drag(
            start=Point(x=10, y=10), end=Point(x=200, y=200), duration=0.1
        )
    assert commands[-1]["type"] == "mouseReleased"
    assert commands[-1]["buttons"] == 0


def _rest(devices, tab, point):
    rest = devices.mouse._rest(tab)
    rest.position, rest.placed = point, True


def _devices(focus: Callable[[], Tab | None]) -> Input:
    """Input paced like a person and watched by people, so it is reported."""
    devices = Input(lambda: None if (tab := focus()) is None else tab.input)
    devices.pace(HumanMotor())
    devices.present(Stage())
    return devices


def _rig(*, dispatch=None):
    tab, events, commands = _tab(dispatch=dispatch)
    return _devices(lambda: tab), tab, events, commands


def _tab(target_id="tab-1", *, dispatch=None, events=None, viewport=(1000, 600)):
    events = [] if events is None else events
    commands = []

    async def emit(event):
        EventRegistry(INPUT_EVENTS + SCENE_EVENTS).validate(event)
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
                    css_layout_viewport=SimpleNamespace(
                        client_width=width, client_height=height
                    )
                )
            )
        ),
    )
    return Tab(target_id, cdp, emit=emit), events, commands


async def test_first_tab_seeds_the_pointer_without_a_tab_press(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(mouse_module.asyncio, "sleep", sleep)
    tab, events, commands = _tab()
    focus: dict[str, Tab | None] = {"tab": None}
    devices = _devices(lambda: focus["tab"])

    async def switch():
        focus["tab"] = tab

    await devices.mouse.switch_tab(TabGesture.ACTIVATE, tab.id, switch)
    assert devices.mouse.position_in(tab.id) == Point(x=500, y=300)
    assert [(c["type"], c["x"], c["y"]) for c in commands] == [("mouseMoved", 500, 300)]
    assert [type(event) for event in events] == [CursorStateEvent]
    assert (events[0].x, events[0].y) == (500, 300) and events[0].target_id == tab.id
    sleep.assert_not_awaited()


async def test_tab_switch_presses_the_tab_then_enters_the_new_page(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(mouse_module.asyncio, "sleep", sleep)
    events = []
    first, _, first_commands = _tab("first", events=events)
    second, _, second_commands = _tab("second", events=events)
    focus = {"tab": first}
    devices = _devices(lambda: focus["tab"])
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
    assert [(c["type"], c["x"], c["y"]) for c in second_commands] == [
        ("mouseMoved", 500, 300)
    ]


async def test_returning_to_a_tab_lands_where_its_pointer_rested(monkeypatch):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
    events = []
    first, _, first_commands = _tab("first", events=events)
    second, _, _ = _tab("second", events=events)
    focus = {"tab": second}
    devices = _devices(lambda: focus["tab"])
    _rest(devices, first, Point(x=100, y=80))
    _rest(devices, second, Point(x=700, y=400))

    async def switch():
        focus["tab"] = first

    await devices.mouse.switch_tab(TabGesture.CLOSE, "second", switch)
    pressed = next(event for event in events if isinstance(event, TabPressedEvent))
    assert pressed.gesture is TabGesture.CLOSE and pressed.from_position == (700, 400)
    entered = next(event for event in events if isinstance(event, CursorEnteredEvent))
    assert entered.to_position == (100, 80)
    assert [(c["x"], c["y"]) for c in first_commands] == [(100, 80)]


async def test_a_gesture_stays_on_the_tab_where_it_started(monkeypatch):
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
    second, _, second_commands = _tab("second")
    focus = {}

    async def dispatch(arguments):
        if arguments.get("buttons") == 1:
            focus["tab"] = second

    first, _, first_commands = _tab("first", dispatch=dispatch)
    focus["tab"] = first
    devices = _devices(lambda: focus["tab"])
    await devices.mouse.drag(
        start=Point(x=10, y=10), end=Point(x=200, y=200), duration=0.1
    )
    assert first_commands[-1]["type"] == "mouseReleased"
    assert not second_commands
    assert devices.mouse.position_in(first.id) == Point(x=200, y=200)
    assert devices.mouse.position_in(second.id) is None


async def test_input_without_a_focused_tab_is_rejected():
    devices = _devices(lambda: None)
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
    monkeypatch.setattr(mouse_module.asyncio, "sleep", AsyncMock())
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


async def test_unwatched_input_reports_nothing_and_never_pauses(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    tab, events, commands = _tab()
    focus: dict[str, Tab | None] = {"tab": None}
    devices = Input(lambda: None if (tab := focus["tab"]) is None else tab.input)

    async def switch():
        focus["tab"] = tab

    await devices.mouse.switch_tab(TabGesture.OPEN, "", switch)
    await devices.mouse.move_to(Point(x=300, y=0))
    await devices.keyboard.type_text("ab")
    assert not events
    sleep.assert_not_awaited()
    # Straight to the target: one native move each, the first in the viewport's middle.
    moves = [(c["x"], c["y"]) for c in commands if c["type"] == "mouseMoved"]
    assert moves == [(500, 300), (300, 0)]


def test_restoring_a_presenter_brings_back_the_previous_one():
    devices = Input(lambda: None)
    watched = Stage()
    restore = devices.present(watched)
    assert devices.presenter() is watched
    restore()
    assert isinstance(devices.presenter(), Unseen)


def test_restoring_a_motor_brings_back_the_previous_one():
    devices = Input(lambda: None)
    human = HumanMotor()
    restore = devices.pace(human)
    assert devices.motor() is human
    restore()
    assert isinstance(devices.motor(), Instant)


@pytest.mark.parametrize(
    "install,selected,create",
    [("pace", "motor", Instant), ("present", "presenter", Unseen)],
)
@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
@pytest.mark.parametrize("shared", [False, True])
def test_input_overrides_can_be_removed_independently(
    install, selected, create, order, shared
):
    devices = Input(lambda: None)
    current = getattr(devices, selected)
    original = current()
    first = create()
    second = first if shared else create()
    register = getattr(devices, install)
    undo = (register(first), register(second))
    assert current() is second
    undo[order[0]]()
    assert current() is (second if order[0] == 0 else first)
    undo[order[0]]()
    assert current() is (second if order[0] == 0 else first)
    undo[order[1]]()
    assert current() is original
    undo[order[1]]()
    assert current() is original


class _SlowMotor:
    """A motor unlike any built in: slow keys, fixed paths, corner landings."""

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> tuple[KeyStroke, ...]:
        return tuple(KeyStroke(key, 0.2) for key in text)

    def pointer_route(self, start: Point, destination: Point) -> tuple[CursorPath, ...]:
        return (CursorPath.curved(start, destination, 1 / 30),)

    def aim_fractions(  # pylint: disable=unused-argument
        self, target_width: float, target_height: float
    ) -> tuple[float, float]:
        return CENTER

    def press(self) -> float:
        return 0

    def landing(self, width: float, height: float) -> Point:
        return Point(x=width - 1, y=height - 1)


class _Clock:
    """Time that moves only while input waits or the browser is busy."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _clocked(monkeypatch) -> tuple[_Clock, AsyncMock]:
    clock = _Clock()
    sleep = AsyncMock(side_effect=clock.sleep)
    monkeypatch.setattr(mouse_module, "monotonic", clock.time)
    monkeypatch.setattr(mouse_module.asyncio, "sleep", sleep)
    return clock, sleep


class _Steady(Instant):
    """One straight stroke of 0.3 seconds, 18 frames at 60 Hz."""

    def pointer_route(self, start: Point, destination: Point) -> tuple[CursorPath, ...]:
        return (CursorPath.curved(start, destination, 0.3, bend=(0, 0)),)


async def test_a_slow_browser_skips_frames_instead_of_stretching_the_stroke(
    monkeypatch,
):
    clock, _sleep = _clocked(monkeypatch)

    async def slow(_arguments):
        clock.now += 0.02

    devices, _tab, events, commands = _rig(dispatch=slow)
    devices.pace(_Steady())
    await devices.mouse.move_to(Point(x=300, y=0))
    stroke = next(event for event in events if isinstance(event, CursorMovedEvent))
    assert stroke.duration == 0.3
    xs = [c["x"] for c in commands if c["type"] == "mouseMoved"]
    # Late frames are skipped, the rest still follow the path to its end.
    assert len(xs) < 18 and xs == sorted(xs) and xs[-1] == 300
    # Viewers finish the stroke after 0.3 seconds; the pointer at most one dispatch later.
    assert clock.now <= 0.3 + 0.02 + 1e-9


async def test_a_fast_browser_moves_the_pointer_on_every_frame(monkeypatch):
    clock, _sleep = _clocked(monkeypatch)
    devices, _tab, _events, commands = _rig()
    devices.pace(_Steady())
    await devices.mouse.move_to(Point(x=300, y=0))
    moves = [c for c in commands if c["type"] == "mouseMoved"]
    assert len(moves) == 18 and moves[-1]["x"] == 300
    assert clock.now == pytest.approx(0.3)


async def test_a_motor_paces_input_that_nobody_watches(monkeypatch):
    _clock, sleep = _clocked(monkeypatch)
    tab, events, commands = _tab()
    focus: dict[str, Tab | None] = {"tab": None}
    devices = Input(lambda: None if (tab := focus["tab"]) is None else tab.input)
    devices.pace(_SlowMotor())

    async def switch():
        focus["tab"] = tab

    await devices.mouse.switch_tab(TabGesture.ACTIVATE, tab.id, switch)
    await devices.mouse.move_to(Point(x=10, y=10))
    await devices.keyboard.type_text("ab")
    assert not events
    assert devices.mouse.position_in(tab.id) == Point(x=10, y=10)
    moves = [(c["x"], c["y"]) for c in commands if c["type"] == "mouseMoved"]
    assert moves[0] == (999, 599) and len(moves) == 3
    # Two frames along the path, then one pause after each key.
    assert [call.args[0] for call in sleep.await_args_list] == pytest.approx(
        [1 / 60, 1 / 60, 0.2, 0.2]
    )


class _Detour(Instant):
    """Goes round a corner on the way, and holds the button down for each click."""

    def __init__(self, *, hold: float = 0) -> None:
        self._hold = hold

    def pointer_route(self, start: Point, destination: Point) -> tuple[CursorPath, ...]:
        corner = Point(x=destination.x, y=start.y)
        return (
            CursorPath.curved(start, corner, 0),
            CursorPath.curved(corner, destination, 0),
        )

    def press(self) -> float:
        return self._hold


class _Gapped(Instant):
    """Lifts the pointer halfway, which no hand can do."""

    def pointer_route(self, start: Point, destination: Point) -> tuple[CursorPath, ...]:
        return (
            CursorPath.curved(start, Point(x=50, y=0), 0),
            CursorPath.curved(Point(x=60, y=0), destination, 0),
        )


async def test_a_route_moves_the_pointer_stroke_by_stroke():
    devices, tab, events, commands = _rig()
    devices.pace(_Detour())
    await devices.mouse.move_to(Point(x=100, y=60))
    moves = [(c["x"], c["y"]) for c in commands if c["type"] == "mouseMoved"]
    assert moves == [(100, 0), (100, 60)]
    strokes = [event for event in events if isinstance(event, CursorMovedEvent)]
    assert [(e.from_position, e.to_position) for e in strokes] == [
        ((0, 0), (100, 0)),
        ((100, 0), (100, 60)),
    ]
    assert devices.mouse.position_in(tab.id) == Point(x=100, y=60)


async def test_a_broken_route_is_refused_before_the_pointer_moves():
    devices, _tab, events, commands = _rig()
    devices.pace(_Gapped())
    with pytest.raises(BrowserError, match="starts where the last ended"):
        await devices.mouse.move_to(Point(x=100, y=60))
    assert not commands and not events


async def test_a_click_holds_the_button_as_long_as_the_motor_presses(monkeypatch):
    devices, _tab, _events, commands = _rig()
    devices.pace(_Detour(hold=0.12))

    async def hold(seconds):
        commands.append({"type": f"hold {seconds}"})

    monkeypatch.setattr(mouse_module.asyncio, "sleep", hold)
    await devices.mouse.click(Point(x=0, y=0))
    assert [c["type"] for c in commands] == [
        "mouseMoved",
        "mouseMoved",
        "mousePressed",
        "hold 0.12",
        "mouseReleased",
    ]


class _Slipping(Instant):
    """Types whatever keys it was given, regardless of the text asked for."""

    def __init__(self, *keys: str) -> None:
        self._keys = keys

    def keystrokes(  # pylint: disable=unused-argument
        self, text: str, *, sensitive: bool
    ) -> tuple[KeyStroke, ...]:
        return tuple(KeyStroke(key) for key in self._keys)


async def test_a_corrected_slip_enters_the_text_asked_for():
    devices, _tab, events, commands = _rig()
    devices.pace(_Slipping("a", "x", "Backspace", "b"))
    typed = await devices.keyboard.type_text("ab")
    assert typed.exact and typed.entered == "ab"
    keys = [event.key for event in events if isinstance(event, KeyPressedEvent)]
    assert keys == ["a", "x", "Backspace", "b"]
    assert [c["text"] for c in commands if c["type"] == "char"] == ["a", "x", "b"]


async def test_send_keys_reports_a_slip_that_stayed():
    devices, _tab, _events, _commands = _rig()
    devices.pace(_Slipping("h", "e", "l", "o"))

    tools = SimpleNamespace(
        _browser=SimpleNamespace(input=devices),
        _secrets=None,
        _actions=_DirectActions(),
    )
    reply = await KeyboardTools.send_keys(tools, text="hello")
    assert "typed 'helo' instead of 'hello'" in reply.text


@pytest.mark.parametrize(
    "keys",
    [("p", "x", "Backspace", "w"), ("p",), ("p", "w", "!")],
)
async def test_sensitive_text_refuses_a_plan_that_is_not_exact(keys):
    devices, _tab, events, commands = _rig()
    devices.pace(_Slipping(*keys))
    with pytest.raises(BrowserError, match="exactly"):
        await devices.keyboard.type_text("pw", sensitive=True)
    assert not commands and not events


@pytest.mark.parametrize(
    "keys,message",
    [(("Backspace", "a"), "only erase"), (("Enter",), "not 'Enter'")],
)
async def test_a_plan_the_keyboard_cannot_follow_is_refused_before_any_key(
    keys, message
):
    devices, _tab, _events, commands = _rig()
    devices.pace(_Slipping(*keys))
    with pytest.raises(BrowserError, match=message):
        await devices.keyboard.type_text("a")
    assert not commands


class _DirectActions:
    """Device tests execute input directly without a mounted action lifecycle."""

    async def dispatch(self, operation):
        return await operation()
