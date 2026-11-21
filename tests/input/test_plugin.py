import asyncio
from dataclasses import dataclass, field

import pytest
from harnessed import Agent, Plugin
from harnessed.errors import PluginDependencyError
from harnessed.plugins import Service
from harnessed.sessions.log import SessionLog
from harnessed.testing import ScriptedModel

from browserrig import (
    ActionContext,
    Browser,
    ChangeTab,
    Input,
    InputPacing,
    InputRuntime,
    InputTargets,
    Point,
    Runtime,
)
from browserrig.core import BrowserError, TabGesture, ViewportSize
from browserrig.events import TabActivatedEvent, TabClosedEvent
from browserrig.input import CursorPath, HumanMotor, Instant, KeyStroke


async def test_devices_can_run_against_a_transport_without_a_browser():
    ports = _Targets()
    agent = _agent(ports)
    async with agent.session() as session:
        assert Browser not in session.scope
        devices = session.scope[Input]
        target = _Transport("first")

        async def open_target():
            ports.active = target

        await session.scope.dispatch(
            ChangeTab(TabGesture.OPEN, ""), default=open_target
        )
        assert devices.mouse.position == Point(x=50, y=40)
        await devices.mouse.move_to(Point(x=7, y=9))
        await devices.keyboard.press_key("Enter")
        assert target.mouse[-1] == Point(x=7, y=9)
        assert target.keys == ["Enter", "Enter"]


async def test_initial_focus_is_synchronized_and_closed_targets_are_forgotten():
    target = _Transport("first")
    ports = _Targets(target)
    async with _agent(ports).session() as session:
        devices = session.scope[Input]
        assert target.mouse == [Point(x=50, y=40)]
        await devices.mouse.move_to(Point(x=7, y=9))
        await session.scope[SessionLog].emit(TabActivatedEvent(target_id=target.id))
        assert target.mouse == [Point(x=50, y=40), Point(x=7, y=9)]
        ports.active = None
        await session.scope[SessionLog].emit(TabClosedEvent(target_id=target.id))
        assert devices.mouse.position_in(target.id) is None


async def test_cancelled_tab_operation_does_not_disable_later_focus_synchronization():
    ports = _Targets()
    async with _agent(ports).session() as session:
        actions = session.scope[ActionContext]

        async def cancelled():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError), actions.activate("cancelled"):
            await session.scope.dispatch(
                ChangeTab(TabGesture.OPEN, ""), default=cancelled
            )
        ports.active = _Transport("recovered")
        await session.scope[SessionLog].emit(TabActivatedEvent(target_id="recovered"))
        assert session.scope[Input].mouse.position == Point(x=50, y=40)
        assert actions.action_id == ""


async def test_pacing_can_change_landing_without_a_browser_dependency():
    ports = _Targets()
    async with _agent(ports, InputPacing(_Corner())).session() as session:

        async def open_target():
            ports.active = _Transport("paced")

        await session.scope.dispatch(
            ChangeTab(TabGesture.OPEN, ""), default=open_target
        )
        assert session.scope[Input].mouse.position == Point(x=3, y=5)


async def test_pacing_mount_controls_wheel_input_and_unmount_restores_instant():
    target = _Transport("wheel")
    async with _agent(_Targets(target)).session() as session:
        devices = session.scope[Input]
        await devices.mouse.scroll(delta_y=120)
        assert target.wheels == [(0, 120)]
        target.wheels.clear()
        pacing = await session.mount(InputPacing(HumanMotor()))
        await devices.mouse.scroll(delta_y=120)
        assert len(target.wheels) > 1
        assert sum(dy for _dx, dy in target.wheels) == pytest.approx(120)
        await pacing.aclose()
        await session.scope.settle()
        target.wheels.clear()
        await devices.mouse.scroll(delta_y=120)
        assert target.wheels == [(0, 120)]


@pytest.mark.parametrize("typing,route", [(True, False), (False, True), (True, True)])
async def test_planners_override_independently_and_restore_the_session_motor(
    typing, route
):
    calls = []

    def keys(text, *, sensitive):
        calls.append(("keys", text, sensitive))
        return (KeyStroke("b"),)

    def path(start, destination):
        calls.append(("path", start, destination))
        return (CursorPath.curved(start, destination, 0),)

    target = _Transport("planned")
    destination = Point(x=8, y=12)
    drag_start = Point(x=10, y=10)
    drag_end = Point(x=20, y=20)
    async with _agent(_Targets(target)).session() as session:
        devices = session.scope[Input]
        original = devices.motor()
        handle = await session.mount(
            InputPacing(
                _Corner(),
                keystrokes=keys if typing else None,
                cursor_route=path if route else None,
            )
        )
        assert devices.motor().landing(80, 60) == Point(x=3, y=5)
        start = devices.mouse.position
        await devices.mouse.move_to(destination)
        assert target.mouse[-1] == destination
        await devices.mouse.drag(start=drag_start, end=drag_end)
        assert target.mouse[-1] == drag_end
        result = await devices.keyboard.type_text("a")
        assert result.entered == ("b" if typing else "a")
        if typing:
            with pytest.raises(
                BrowserError, match="Sensitive text must be typed exactly"
            ):
                await devices.keyboard.type_text("a", sensitive=True)
        expected = (
            [
                ("path", start, destination),
                ("path", drag_start, drag_end),
                ("path", destination, drag_start),
            ]
            if route
            else []
        )
        if typing:
            expected.extend([("keys", "a", False), ("keys", "a", True)])
        assert calls == expected
        await handle.aclose()
        await session.scope.settle()
        assert devices.motor() is original


async def test_missing_transport_is_reported_before_model_use():
    model = ScriptedModel([])
    agent = Agent(model=model, plugins=[Runtime(), InputRuntime()])
    with pytest.raises(
        PluginDependencyError, match="InputRuntime requires InputTargets"
    ):
        await agent.run("Act")
    assert not model.requests


async def test_replacing_transport_rebuilds_devices_and_keeps_runtime_correlation():
    first = _Targets(_Transport("first"))
    second = _Targets(_Transport("second"))
    async with _agent(first).session() as session:
        actions = session.scope[ActionContext]
        original = session.scope[Input]
        await original.mouse.move_to(Point(x=7, y=9))
        handle = await session.mount(Service(InputTargets, second))
        replacement = session.scope[Input]
        assert replacement is not original
        assert replacement.mouse.position == Point(x=50, y=40)
        with actions.activate("shared"):
            assert session.scope[ActionContext].action_id == "shared"
        await handle.aclose()
        await session.scope.settle()
        assert session.scope[Input] is not replacement
        assert session.scope[Input].mouse.position_in("second") is None
        assert session.scope[ActionContext] is actions


def _agent(ports, *plugins):
    return Agent(
        model=ScriptedModel([]),
        plugins=[Runtime(), _Backend(ports), InputRuntime(), *plugins],
    )


@dataclass
class _Targets:
    active: object | None = None

    def focused(self):
        return self.active


@dataclass
class _Transport:
    id: str
    mouse: list[Point] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    wheels: list[tuple[float, float]] = field(default_factory=list)

    async def viewport_size(self):
        return ViewportSize(width=100, height=80)

    async def dispatch_mouse(self, _kind, point, **_kwargs):
        self.mouse.append(point)

    async def dispatch_key(self, _kind, *, key, **_kwargs):
        self.keys.append(key)

    async def dispatch_wheel(self, _point, *, delta_x, delta_y):
        self.wheels.append((delta_x, delta_y))

    def layout_changed(self):
        pass


class _Corner(Instant):
    def landing(self, viewport_width, viewport_height):
        return Point(x=3, y=5)


class _Backend(Plugin):
    events = (TabActivatedEvent, TabClosedEvent)

    def __init__(self, targets):
        super().__init__()
        self._targets = targets

    async def setup(self, scope):
        scope.provide(InputTargets, self._targets)
