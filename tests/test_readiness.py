# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

import asyncio
import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Context, Inject, Plugin
from harnessed.testing import ScriptedModel
from PIL import Image

from browserrig import CanvasMode, Readiness, ReadinessOptions, wait_for_page
from browserrig.core.geometry import Geometry
from browserrig.events import ReadinessDegradedEvent, ReadinessStartedEvent, ReadyEvent
from browserrig.readiness.canvas import CanvasProbe, _has_canvas_content
from tests.fakes import FakeBrowser, FakeChrome


class Access(Plugin, needs=(Readiness,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, _ctx: Context, readiness: Inject[Readiness]):
        self.holder["readiness"] = readiness


async def test_readiness_deduplicates_waiters_and_one_cancellation_does_not_cancel_other():
    holder = {}
    options = ReadinessOptions(quiet_ms=0, navigation_min_ms=40, poll_interval=0.005)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options), Access(holder)],
    )
    async with agent.session() as session:
        readiness, tab = holder["readiness"], holder["browser"].active_tab
        first = asyncio.create_task(readiness.wait(tab, phase="initial"))
        second = asyncio.create_task(readiness.wait(tab, phase="initial"))
        await asyncio.sleep(0.005)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        report = await second
        assert report.status == "ready"
        assert len([e for e in session.events if isinstance(e, ReadinessStartedEvent)]) == 1


async def test_endless_dom_mutation_is_explicitly_degraded():
    holder = {}
    options = ReadinessOptions(timeout=0.03, poll_interval=0.005, navigation_min_ms=0)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options), Access(holder)],
    )
    async with agent.session() as session:
        holder["browser"].active_tab.quiet_ms = 0
        report = await holder["readiness"].wait(holder["browser"].active_tab)
        assert report.status == "degraded"
        assert "changing" in report.reason
        assert any(isinstance(e, ReadinessDegradedEvent) for e in session.events)


async def test_plugin_state_is_per_session():
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]), plugins=[Access(holder), Readiness(), FakeChrome(holder)]
    )
    async with agent.session("first"):
        first = holder["readiness"]
        first_events = first._events
        assert first_events is holder["browser"].events
        first._state.geometry[("sentinel", "doc")] = object()
    async with agent.session("second"):
        second = holder["readiness"]
        assert second is not first
        assert second._events is holder["browser"].events
        assert second._events is not first_events
        assert not second._state.geometry
    with pytest.raises(RuntimeError):
        _ = first._events


@pytest.mark.parametrize("changed", [False, True])
async def test_canvas_reuses_cached_geometry_and_rechecks_pixels_only_after_geometry_changes(
    monkeypatch, changed
):
    browser = FakeBrowser(SimpleNamespace(emit=AsyncMock()))
    tab = browser.active_tab
    tab.quiet_ms = 0
    original = Geometry(width=500, height=400)
    current = original.model_copy(update={"width": 600}) if changed else original
    cache = {(tab.id, tab.document_id): original}
    locate = AsyncMock(return_value=CanvasProbe(ready=True, geometry=current))
    pixels = AsyncMock(return_value=(current, ""))
    monkeypatch.setattr("browserrig.readiness.canvas._locate_canvas", locate)
    monkeypatch.setattr("browserrig.readiness.canvas._probe_canvas", pixels)
    report = await wait_for_page(
        tab,
        mode=CanvasMode(),
        options=ReadinessOptions(timeout=2),
        geometry_cache=cache,
    )
    assert report.status == "ready"
    assert report.geometry == current
    assert cache[(tab.id, tab.document_id)] == current
    assert locate.await_count == 1
    assert pixels.await_count == (2 if changed else 0)


def test_canvas_zero_color_fraction_rejects_low_contrast_without_crashing():
    image = Image.new("RGB", (20, 20), (120, 120, 120))
    image.paste((130, 130, 130), (0, 0, 10, 20))
    output = BytesIO()
    image.save(output, format="PNG")
    assert not _has_canvas_content(base64.b64encode(output.getvalue()).decode(), 0)


async def test_readiness_events_keep_start_document_when_navigation_finishes(monkeypatch):
    events = []
    browser = FakeBrowser(SimpleNamespace(emit=AsyncMock(side_effect=events.append)))
    tab = browser.active_tab

    async def check(_strategy):
        tab.document_id = "new-document"
        return True

    monkeypatch.setattr("browserrig.readiness.wait._check", check)
    report = await wait_for_page(tab, events=browser.events)
    start = next(event for event in events if isinstance(event, ReadinessStartedEvent))
    end = next(event for event in events if isinstance(event, ReadyEvent))
    assert start.readiness_id == end.readiness_id
    assert start.document_id == end.document_id == "doc-1"
    assert report.document_id == "new-document"
