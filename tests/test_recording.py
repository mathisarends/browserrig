# Lifecycle assertions use recording state alongside durable receipts.
# pylint: disable=protected-access

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Inject, Plugin
from harnessed.testing import ScriptedModel

from browserrig import Readiness, Recording, RecordingOptions
from browserrig.core.errors import RecordingError
from browserrig.events import RecordingFailedEvent, RecordingSegmentLostEvent, TabClosedEvent
from tests.fakes import FakeChrome


def _tab(name, *, size=100):
    data = b"\x1aE\xdf\xa3" + b"x" * size
    stream = f"stream-{name}"
    return SimpleNamespace(
        id=name,
        document_id="doc",
        closed=False,
        cdp=SimpleNamespace(
            page=SimpleNamespace(
                start_screen_recording=AsyncMock(return_value=SimpleNamespace(stream=stream)),
                stop_screen_recording=AsyncMock(return_value=SimpleNamespace(stream=stream)),
            ),
            io=SimpleNamespace(
                read=AsyncMock(
                    return_value=SimpleNamespace(
                        data=base64.b64encode(data).decode(), base64_encoded=True, eof=True
                    )
                ),
                close=AsyncMock(),
            ),
        ),
    )


@pytest.fixture(name="recording")
async def _recording(tmp_path):
    holder = {}

    class Chrome(FakeChrome):
        events = (TabClosedEvent,)

    class Access(Plugin, needs=(Recording,)):
        async def setup(self, recorder: Inject[Recording]):
            holder["recording"] = recorder

    agent = Agent(
        model=ScriptedModel(["unused"]),
        plugins=[
            Chrome(holder),
            Readiness(),
            Recording(RecordingOptions(directory=tmp_path, required=True, max_bytes=1024)),
            Access(),
        ],
    )
    async with agent.session() as session:
        yield holder["recording"], session


async def test_closed_tab_loses_segment_without_touching_dead_session_and_can_restart(recording):
    recorder, session = recording
    closed = _tab("closed")
    await recorder.ensure_started(closed)
    closed.closed = True
    await session.emit(TabClosedEvent(target_id=closed.id))
    closed.cdp.page.stop_screen_recording.assert_not_awaited()
    closed.cdp.io.close.assert_not_awaited()
    assert recorder._state.tab is None and not recorder._state.failed
    assert (
        len([event for event in session.events if isinstance(event, RecordingSegmentLostEvent)])
        == 1
    )
    next_tab = _tab("next")
    await recorder.ensure_started(next_tab)
    await recorder._stop()
    assert len(recorder._state.segments) == 1
    assert not any(isinstance(event, RecordingFailedEvent) for event in session.events)


async def test_oversized_segment_is_cleaned_up_and_later_recording_succeeds(recording):
    recorder, session = recording
    await recorder.ensure_started(_tab("oversized", size=2048))
    await recorder._stop()
    assert not recorder._state.failed
    assert not list(recorder._state.directory.glob("*.partial"))
    lost = next(event for event in session.events if isinstance(event, RecordingSegmentLostEvent))
    assert "max_bytes" in lost.reason
    await recorder.ensure_started(_tab("next"))
    await recorder._finalize()
    manifest = json.loads((recorder._state.directory / "manifest.json").read_text())
    assert not manifest["failed"] and len(manifest["segments"]) == 1
    assert len(manifest["lost_segments"]) == 1


async def test_required_recording_still_fails_when_backend_cannot_start(recording):
    recorder, _session = recording
    tab = _tab("broken")
    tab.cdp.page.start_screen_recording.side_effect = RuntimeError("backend unavailable")
    with pytest.raises(RecordingError, match="backend unavailable"):
        await recorder.ensure_started(tab)
    assert recorder._state.failed


async def test_cancelled_finalization_closes_and_removes_partial_segment(recording):
    recorder, session = recording
    tab = _tab("cancelled")
    entered = asyncio.Event()

    async def read(**_kwargs):
        entered.set()
        await asyncio.Event().wait()

    tab.cdp.io.read.side_effect = read
    await recorder.ensure_started(tab)
    task = asyncio.create_task(recorder._stop())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(recorder._state.directory.glob("*.partial"))
    assert recorder._state.tab is None and not recorder._state.failed
    assert any(isinstance(event, RecordingSegmentLostEvent) for event in session.events)
