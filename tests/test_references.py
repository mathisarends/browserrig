import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from harnessed import Agent, Plugin, PluginOrder, SystemPrompt, ToolError
from harnessed.testing import ScriptedModel

from browserrig import (
    BrowserPerception,
    CaptureContent,
    ElementInfo,
    ElementRef,
    PageContent,
    Readiness,
    ScrollStep,
)
from browserrig.core import Bounds, BrowserError, ElementPoint, Point, StaleElement
from browserrig.events import ActionFailedEvent
from browserrig.input import Instant
from browserrig.kinds import MouseEventKind
from browserrig.observation import (
    DomElementHandle,
    DomReferences,
    Element,
    Snapshot,
    render,
)
from browserrig.observation.models import Offscreen
from browserrig.tools import (
    Actions,
    FileTools,
    FormTools,
    KeyboardTools,
    PointerTools,
)
from browserrig.tools.scrolling import prepare_element
from tests.fakes import FakeChrome, FakeReadiness, FakeTab


async def test_dom_and_backend_data_round_trip_without_runtime_resolvers():
    async with _observed(_Backend()) as env:
        snapshot = env.observe.snapshot
        native = Element(
            ref="native",
            frame_id="frame",
            backend_id=12,
            role="button",
            name="Native",
            tag="button",
        )
        snapshot = snapshot.model_copy(
            update={
                "elements": (*snapshot.elements, native),
                "offscreen": (
                    ElementRef(ref="hidden"),
                    Offscreen(ref="below", frame_id="frame", backend_id=13),
                ),
            }
        )
        restored = Snapshot.model_validate_json(snapshot.model_dump_json())
        assert isinstance(restored.element("shape/a"), ElementInfo)
        assert not hasattr(restored.element("shape/a"), "backend_id")
        assert isinstance(restored.element("native"), Element)
        assert restored.element("native").backend_id == 12
        assert isinstance(restored.offscreen[0], ElementRef)
        assert not hasattr(restored.offscreen[0], "backend_id")
        assert isinstance(restored.offscreen[1], Offscreen)
        assert "references" not in restored.model_dump()
        assert '[shape/a] button "Shape A"' in render(restored)


async def test_backend_locates_live_geometry_and_uses_the_common_motor_aim():
    backend = _Backend()
    motor = _Aiming()
    async with _observed(backend) as env:
        env.browser.input.pace(motor)
        backend.objects["shape/a"] = Bounds(x=200, y=100, width=100, height=40)
        with env.browser.input.action("aim"):
            point = await env.actions.element_point(tab=env.tab, ref="shape/a")
            again = await env.actions.element_point(
                tab=env.tab, ref="shape/a", scroll=False
            )
        assert (point.x, point.y) == (225, 130)
        assert again == point
        assert motor.sizes == [(100, 40)]
        assert backend.aims == [(0.25, 0.75), (0.25, 0.75)]
        env.tab.frames.assert_not_awaited()
        env.tab.dispatch_mouse.assert_not_awaited()


async def test_probe_keeps_the_published_refs_until_a_full_capture():
    backend = _Backend()
    async with _observed(backend) as env:
        original, references = env.observe.snapshot, env.observe.references
        backend.objects["new/item"] = Bounds(x=250, y=50, width=50, height=30)
        probe = await env.observe.probe(env.tab)
        assert probe.element("new/item").ref == "new/item"
        assert env.observe.snapshot is original
        assert env.observe.references is references
        assert backend.resolvers[-1] is not references
        with pytest.raises(StaleElement, match="Unknown"):
            await env.observe.element(env.tab, "new/item")
        fresh = await env.observe.capture()
        handle = await env.observe.element(env.tab, "new/item")
        assert handle.element is fresh.element("new/item")
        assert env.observe.references is backend.resolvers[-1]
        assert env.observe.references is not references


@pytest.mark.parametrize(
    "invalid", ["unknown", "offscreen", "tab", "document", "invalidate"]
)
async def test_invalid_refs_are_rejected_before_the_backend_is_called(invalid):
    backend = _Backend()
    backend.offscreen = (ElementRef(ref="hidden"),)
    async with _observed(backend) as env:
        tab, ref = env.tab, "shape/a"
        references = env.observe.references
        if invalid == "unknown":
            ref = "missing"
        elif invalid == "offscreen":
            ref = "hidden"
        elif invalid == "tab":
            tab = FakeTab()
            tab.id = "another-tab"
        elif invalid == "document":
            tab.document_id = "another-document"
        else:
            env.observe.invalidate()
        with pytest.raises(StaleElement):
            await env.observe.element(tab, ref)
        assert references.resolved == []
        env.tab.dispatch_mouse.assert_not_awaited()


async def test_a_removed_backend_object_cannot_be_located_with_an_old_handle():
    backend = _Backend()
    async with _observed(backend) as env:
        handle = await env.observe.element(env.tab, "shape/a")
        del backend.objects["shape/a"]
        with pytest.raises(StaleElement, match="no longer exists"):
            await handle.locate()
        env.tab.dispatch_mouse.assert_not_awaited()


async def test_refs_removed_from_a_new_capture_do_not_reuse_old_bindings():
    backend = _Backend()
    async with _observed(backend) as env:
        backend.objects = {"another/ref": Bounds(x=10, y=20, width=30, height=40)}
        await env.observe.capture()
        with pytest.raises(StaleElement, match="Unknown"):
            await env.observe.element(env.tab, "shape/a")
        assert env.observe.references.resolved == []
        handle = await env.observe.element(env.tab, "another/ref")
        assert handle.element.ref == "another/ref"


async def test_non_dom_data_needs_a_resolver_instead_of_invented_dom_addresses():
    backend = _Backend()
    backend.use_references = False
    async with _observed(backend) as env:
        with pytest.raises(BrowserError, match="must supply References"):
            await env.observe.element(env.tab, "shape/a")
        env.tab.frames.assert_not_awaited()


async def test_dom_capabilities_are_checked_per_target_in_a_mixed_capture():
    backend = _Backend()
    backend.extra_elements = (
        Element(
            ref="native",
            frame_id="native-frame",
            backend_id=5,
            role="combobox",
            name="Choice",
            tag="select",
        ),
    )
    async with _observed(backend) as env:
        frame = SimpleNamespace(id="native-frame")
        env.tab.frames.return_value = (frame,)
        env.tab.frames.side_effect = None
        native = await env.observe.dom_element(env.tab, "native")
        assert isinstance(native, DomElementHandle)
        assert native.frame is frame and native.element.backend_id == 5
        with pytest.raises(BrowserError, match="requires a DOM element"):
            await env.observe.dom_element(env.tab, "shape/a")
        env.tab.frames.assert_awaited_once()


@pytest.mark.parametrize("refresh", ["probe", "capture"])
async def test_resolution_keeps_its_capture_binding_across_awaits(refresh):
    async with _observed(_Backend()) as env:
        references = env.observe.references
        original = references.resolve
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked(tab, snapshot, ref):
            entered.set()
            await asyncio.wait_for(release.wait(), 2)
            return await original(tab, snapshot, ref)

        references.resolve = blocked
        task = asyncio.create_task(env.observe.element(env.tab, "shape/a"))
        await asyncio.wait_for(entered.wait(), 2)
        try:
            if refresh == "capture":
                await env.observe.capture()
            else:
                await env.observe.probe(env.tab)
        finally:
            release.set()
        if refresh == "capture":
            with pytest.raises(StaleElement, match="Observation changed"):
                await asyncio.wait_for(task, 2)
        else:
            handle = await asyncio.wait_for(task, 2)
            assert handle.element.ref == "shape/a"


@pytest.mark.parametrize("invalid", ["document", "target"])
async def test_resolver_cannot_change_documents_or_return_another_ref(invalid):
    backend = _Backend()
    async with _observed(backend) as env:
        backend.resolution_error = invalid
        with pytest.raises(StaleElement):
            await env.observe.element(env.tab, "shape/a")
        assert env.observe.references.resolved == ["shape/a"]
        env.tab.dispatch_mouse.assert_not_awaited()


@pytest.mark.parametrize("failure", ["failure", "navigation", "duplicate"])
async def test_failed_capture_keeps_the_previous_snapshot_and_resolver_together(
    failure,
):
    backend = _Backend()
    async with _observed(backend) as env:
        snapshot, references = env.observe.snapshot, env.observe.references
        backend.capture_error = failure
        with pytest.raises(BrowserError):
            await env.observe.capture()
        assert env.observe.snapshot is snapshot
        assert env.observe.references is references
        env.tab.dispatch_mouse.assert_not_awaited()


@pytest.mark.parametrize("tool", ["select", "date", "type", "upload"])
async def test_dom_tools_reject_backend_refs_before_any_input(tool):
    async with _observed(_Backend()) as env:
        with pytest.raises(ToolError, match="requires a DOM element"):
            if tool == "select":
                await env.ctx[_Forms].select_option(
                    "shape/a", "Choice", actions=env.actions
                )
            elif tool == "date":
                await env.ctx[_Forms].set_date(
                    "shape/a", "2026-11-01", actions=env.actions
                )
            elif tool == "type":
                await env.ctx[_Keys].type_text("shape/a", "Text", actions=env.actions)
            else:
                await env.ctx[_Uploads].upload_files(
                    "shape/a", ["file.txt"], actions=env.actions
                )
        env.tab.dispatch_mouse.assert_not_awaited()
        env.tab.dispatch_key.assert_not_awaited()
        env.tab.dispatch_wheel.assert_not_awaited()
        failures = [
            event for event in env.events if isinstance(event, ActionFailedEvent)
        ]
        assert len(failures) == 1 and not failures[0].dispatched


async def test_backend_refs_use_normal_mouse_and_keyboard_and_end_action_chains():
    async with _observed(_Backend()) as env:
        original = env.observe.snapshot
        click = await env.ctx[_Pointer].click("shape/a", actions=env.actions)
        typed = await env.ctx[_Keys].send_keys(text="Hi", actions=env.actions)
        events = env.tab.dispatch_mouse.await_args_list
        assert [
            call.args[0] for call in events if call.args[0] != MouseEventKind.MOVED
        ] == [
            MouseEventKind.PRESSED,
            MouseEventKind.RELEASED,
        ]
        assert all(
            (call.args[1].x, call.args[1].y) == (100, 70)
            for call in events
            if call.args[0] != MouseEventKind.MOVED
        )
        text = "".join(
            call.kwargs.get("text") or ""
            for call in env.tab.dispatch_key.await_args_list
        )
        assert text == "Hi"
        assert click.break_chain and typed.break_chain
        assert env.observe.snapshot is original
        env.tab.frames.assert_not_awaited()


async def test_hover_change_uses_backend_fingerprint_and_prevents_the_click():
    backend = _Backend()
    async with _observed(backend) as env:

        async def moved(kind, _point, **_kwargs):
            if kind == MouseEventKind.MOVED:
                backend.revision += 1

        env.tab.dispatch_mouse.side_effect = moved
        result = await env.ctx[_Pointer].click("shape/a", actions=env.actions)
        assert result.break_chain and "Hover changed" in result.content
        assert env.tab.dispatch_mouse.await_count > 0
        assert all(
            call.args[0] == MouseEventKind.MOVED
            for call in env.tab.dispatch_mouse.await_args_list
        )


async def test_optional_backend_scroll_plan_runs_through_mouse_wheel_input():
    step = ScrollStep(point=Point(x=100, y=70), delta_x=0, delta_y=120, key="step")
    handle = SimpleNamespace(scroll_step=AsyncMock(side_effect=[step, None]))
    async with _observed(_Backend()) as env:
        scrolled = await prepare_element(
            env.tab, handle, env.browser.mouse, document_id=env.tab.document_id
        )
        assert scrolled and handle.scroll_step.await_count == 2
        calls = env.tab.dispatch_wheel.await_args_list
        assert calls and all(call.args[0] == step.point for call in calls)
        assert sum(call.kwargs["delta_y"] for call in calls) == pytest.approx(120)
        env.tab.frames.assert_not_awaited()


async def test_scroll_plan_is_not_executed_after_navigation():
    handle = SimpleNamespace(scroll_step=AsyncMock())
    async with _observed(_Backend()) as env:
        with pytest.raises(StaleElement, match="Document changed"):
            await prepare_element(env.tab, handle, env.browser.mouse, document_id="old")
        handle.scroll_step.assert_not_awaited()
        env.tab.dispatch_wheel.assert_not_awaited()


async def test_a_stalled_backend_scroll_plan_stops_before_repeating_forever():
    step = ScrollStep(point=Point(x=100, y=70), delta_x=0, delta_y=10, key="stalled")
    handle = SimpleNamespace(scroll_step=AsyncMock(return_value=step))
    mouse = SimpleNamespace(scroll=AsyncMock())
    async with _observed(_Backend()) as env:
        with pytest.raises(BrowserError, match="could not be brought into view"):
            await prepare_element(
                env.tab, handle, mouse, document_id=env.tab.document_id
            )
        assert handle.scroll_step.await_count == 3
        assert mouse.scroll.await_count == 2


class _Forms(FormTools, provides=True):
    pass


class _Keys(KeyboardTools, provides=True):
    pass


class _Uploads(FileTools, provides=True):
    pass


class _Pointer(PointerTools, provides=True):
    pass


class _Ready(Plugin):
    async def setup(self, ctx):
        ctx.provide(Readiness, FakeReadiness())


class _Aiming(Instant):
    def __init__(self):
        self.sizes = []

    def aim_fractions(self, target_width, target_height):
        self.sizes.append((target_width, target_height))
        return 0.25, 0.75


class _Backend:
    """A test-only source of opaque targets; no DOM addresses or scripted mutations."""

    def __init__(self):
        self.objects = {"shape/a": Bounds(x=50, y=50, width=100, height=40)}
        self.offscreen = ()
        self.revision = 0
        self.resolvers = []
        self.aims = []
        self.capture_error = None
        self.resolution_error = None
        self.use_references = True
        self.extra_elements = ()

    async def collect(  # pylint: disable=unused-argument
        self, tab, _report, *, screenshots, region=None, zoom=1, cursor=None
    ):
        if self.capture_error == "failure":
            raise BrowserError("Capture failed")
        if self.capture_error == "navigation":
            tab.document_id = "another-document"
        elements = tuple(
            ElementInfo(ref=ref, role="button", name="Shape A", bounds=bounds)
            for ref, bounds in self.objects.items()
        )
        references = _References(self)
        self.resolvers.append(references)
        return CaptureContent(
            page=PageContent(
                url=tab.url,
                title=tab.title,
                width=800,
                height=600,
                scroll_y=0,
                page_height=600,
                elements=(*elements, *self.extra_elements),
                offscreen=(ElementRef(ref="shape/a"),)
                if self.capture_error == "duplicate"
                else self.offscreen,
            ),
            fingerprint=f"revision:{self.revision}",
            references=references if self.use_references else None,
        )


class _References:
    def __init__(self, backend):
        self.backend = backend
        self.resolved = []

    async def resolve(self, tab, snapshot, ref):
        self.resolved.append(ref)
        element = snapshot.element(ref)
        if isinstance(element, Element):
            references = DomReferences()
            return await references.resolve(tab, snapshot, ref)
        if self.backend.resolution_error == "document":
            tab.document_id = "another-document"
        if self.backend.resolution_error == "target":
            element = element.model_copy(update={"ref": "wrong"})
        return _Handle(element, self.backend)


@dataclass
class _Handle:
    element: ElementInfo
    backend: _Backend

    async def locate(self, *, aim=None):
        self.backend.aims.append(aim)
        bounds = self.backend.objects.get(self.element.ref)
        if bounds is None:
            raise StaleElement("Target no longer exists")
        fx, fy = aim if aim is not None else (0.5, 0.5)
        return ElementPoint(
            x=bounds.x + fx * bounds.width,
            y=bounds.y + fy * bounds.height,
            bounds=bounds,
        )


@asynccontextmanager
async def _observed(backend):
    holder, events = {}, []
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=ScriptedModel(["Done"]),
        plugins=[
            FakeChrome(holder),
            _Ready(),
            BrowserPerception(capture=backend),
            Actions(),
            _Forms(),
            _Keys(),
            _Uploads(),
            _Pointer(),
        ],
    )
    async with agent.session() as session:
        browser = holder["browser"]
        browser.tabs.list = AsyncMock(return_value=())
        browser.log = SimpleNamespace(emit=AsyncMock(side_effect=events.append))
        tab = browser.active_tab
        tab.frames = AsyncMock(
            side_effect=AssertionError("Backend must not query DOM frames")
        )
        tab.dispatch_mouse = AsyncMock()
        tab.dispatch_key = AsyncMock()
        tab.dispatch_wheel = AsyncMock()
        tab.viewport_size = AsyncMock(return_value=(800, 600))
        tab.layout_changed = Mock()
        tab.cancel_drag = AsyncMock()
        tab.cursor_style = AsyncMock(return_value=None)
        tab.emit = AsyncMock(side_effect=events.append)
        observe = session.ctx[BrowserPerception]
        await observe.capture()
        yield SimpleNamespace(
            browser=browser,
            tab=tab,
            observe=observe,
            ctx=session.ctx,
            actions=session.ctx[Actions],
            events=events,
        )
