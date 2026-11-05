from base64 import b64encode
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify.exceptions import CDPCommandError
from harnessed import Agent, Context, Plugin
from harnessed.events import ModelRequestedEvent
from harnessed.models import ModelInfo, ModelRequest
from harnessed.testing import ScriptedModel

from browserrig import Activity, Browser, RecordingResult, VideoRecording
from browserrig.activity import plugin as activity_module
from browserrig.core import ActivityKind, ActivityOutcome, BrowserError
from browserrig.events import (
    BROWSER_EVENTS,
    ActivityFinishedEvent,
    ActivityStartedEvent,
    TabActivatedEvent,
    TabClosingEvent,
)
from browserrig.recording import capture as capture_module
from browserrig.recording import plugin as recording_module
from browserrig.recording.capture import Capture
from browserrig.recording.models import Span
from browserrig.recording.timeline import kept_spans


def test_cut_timeline_merges_waits_and_preserves_concurrent_work():
    intervals = (
        _interval(ActivityKind.LLM, 102, 110),
        _interval(ActivityKind.COMPACTION, 104, 112),
        _interval(ActivityKind.TOOL, 106, 108),
        _interval(ActivityKind.READINESS, 107, 109),
        _interval(ActivityKind.PAUSED, 115, 118),
    )
    assert kept_spans(intervals, started_at=100, ended_at=120, padding=0.25) == (
        Span(0, 2.25),
        Span(5.75, 9.25),
        Span(11.75, 15.25),
        Span(17.75, 20),
    )


@pytest.mark.parametrize(
    ("intervals", "expected"),
    [
        ((), (Span(0, 5),)),
        (((90, 102),), (Span(2, 5),)),
        (((103, 120),), (Span(0, 3),)),
        (((90, 120),), ()),
        (((80, 90),), (Span(0, 5),)),
    ],
)
def test_timeline_clips_to_each_capture_and_supports_zero_padding(intervals, expected):
    assert (
        kept_spans(
            (_interval(ActivityKind.LLM, start, end) for start, end in intervals),
            started_at=100,
            ended_at=105,
            padding=0,
        )
        == expected
    )


@pytest.mark.parametrize(
    "options",
    [{"width": 0}, {"height": 321}, {"frame_rate": 0}, {"padding": float("nan")}],
)
def test_configuration_is_validated_without_creating_files(tmp_path, options):
    directory = tmp_path / "recordings"
    with pytest.raises(ValueError):
        VideoRecording(directory, **options)
    assert not directory.exists()


async def test_native_capture_downloads_chunks_and_closes_stream(tmp_path):
    calls = []
    tab = _tab("first", calls)
    tab.cdp.io.read.side_effect = [
        SimpleNamespace(data="header", base64_encoded=False, eof=False),
        SimpleNamespace(
            data=b64encode(b"\x00\xff").decode(), base64_encoded=True, eof=True
        ),
    ]
    capture = Capture(tab, tmp_path / "capture.webm")
    await capture.start(width=640, height=480, frame_rate=15)
    segment = await capture.stop()
    assert segment.path.read_bytes() == b"header\x00\xff"
    assert segment.target_id == "first"
    assert segment.ended_at >= segment.started_at
    tab.cdp.page.start_screen_recording.assert_awaited_once_with(
        audio=False, max_width=640, max_height=480, frame_rate=15
    )
    tab.cdp.page.stop_screen_recording.assert_awaited_once_with()
    tab.cdp.io.close.assert_awaited_once_with(handle="stream-first")
    assert tab.cdp.io.read.await_count == 2


async def test_capture_timeline_starts_after_native_startup(tmp_path, recording_clock):
    tab = _tab("first", [])

    async def start(**_options):
        recording_clock.now = 105.0
        return SimpleNamespace(stream="stream-first")

    tab.cdp.page.start_screen_recording.side_effect = start
    capture = Capture(tab, tmp_path / "capture.mp4")
    await capture.start(width=640, height=480, frame_rate=15)
    recording_clock.now = 110.0
    segment = await capture.stop()
    assert (segment.started_at, segment.ended_at) == (105, 110)
    tab.cdp.page.start_screen_recording.assert_awaited_once()
    tab.cdp.page.stop_screen_recording.assert_awaited_once()


async def test_download_failure_still_closes_native_stream(tmp_path):
    tab = _tab("first", [])
    tab.cdp.io.read.side_effect = OSError("read failed")
    capture = Capture(tab, tmp_path / "capture.webm")
    await capture.start(width=640, height=480, frame_rate=15)
    with pytest.raises(OSError, match="read failed"):
        await capture.stop()
    tab.cdp.page.stop_screen_recording.assert_awaited_once_with()
    tab.cdp.io.read.assert_awaited_once()
    tab.cdp.io.close.assert_awaited_once_with(handle="stream-first")


async def test_unsupported_native_recording_reports_browser_error(tmp_path):
    tab = _tab("first", [])
    tab.cdp.page.start_screen_recording.side_effect = CDPCommandError(
        "Page.startScreenRecording", -32601, "Method not found"
    )
    capture = Capture(tab, tmp_path / "capture.webm")
    with pytest.raises(BrowserError, match="Method not found") as failure:
        await capture.start(width=640, height=480, frame_rate=15)
    assert isinstance(failure.value.__cause__, CDPCommandError)
    tab.cdp.page.start_screen_recording.assert_awaited_once()
    tab.cdp.page.stop_screen_recording.assert_not_awaited()
    assert not list(tmp_path.iterdir())


async def test_session_records_tabs_and_edits_before_browser_cleanup(
    tmp_path, monkeypatch
):
    calls = []
    edits = []
    _install_editor(monkeypatch, edits)
    first, second = _tab("first", calls), _tab("second", calls)
    browser = SimpleNamespace(active_tab=first)
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[Activity(), _BrowserService(browser, calls), VideoRecording(tmp_path)],
    )
    assert not list(tmp_path.iterdir())
    async with agent.session() as session:
        recording = session.ctx[VideoRecording]
        await session.emit(TabActivatedEvent(target_id="first"))
        browser.active_tab = second
        await session.emit(TabActivatedEvent(target_id="second"))
        await session.emit(TabClosingEvent(target_id="second"))
        calls.append("destroy-second")
        browser.active_tab = first
        await session.emit(TabActivatedEvent(target_id="first"))
        assert recording.result is None
    assert calls == [
        "start-first",
        "stop-first",
        "start-second",
        "stop-second",
        "destroy-second",
        "start-first",
        "stop-first",
        "browser-close",
    ]
    assert recording.result.path.read_bytes() == b"edited"
    assert len(recording.result.sources) == 3
    assert len(edits) == 1
    assert [s.target_id for s in edits[0][0]] == ["first", "second", "first"]
    assert all(path.read_bytes() == b"native" for path in recording.result.sources)
    first.cdp.page.start_screen_recording.assert_awaited()
    first.cdp.page.stop_screen_recording.assert_awaited()
    second.cdp.page.start_screen_recording.assert_awaited_once()
    second.cdp.page.stop_screen_recording.assert_awaited_once()


async def test_finish_is_idempotent_and_reusing_agent_isolated(tmp_path, monkeypatch):
    edits = []
    _install_editor(monkeypatch, edits)
    tab = _tab("first", [])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            _BrowserService(SimpleNamespace(active_tab=tab), []),
            VideoRecording(tmp_path),
        ],
    )
    async with agent.session() as session:
        first = await session.ctx[VideoRecording].finish()
        assert await session.ctx[VideoRecording].finish() is first
        await session.emit(TabActivatedEvent(target_id="first"))
    async with agent.session() as session:
        second = await session.ctx[VideoRecording].finish()
    assert first.path != second.path
    assert len(edits) == 2
    assert tab.cdp.page.start_screen_recording.await_count == 2
    assert tab.cdp.page.stop_screen_recording.await_count == 2


async def test_session_exception_finalizes_open_activity(
    tmp_path, monkeypatch, recording_clock
):
    edits = []
    _install_editor(monkeypatch, edits)
    tab = _tab("first", [])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            _BrowserService(SimpleNamespace(active_tab=tab), []),
            VideoRecording(tmp_path, padding=0),
        ],
    )
    with pytest.raises(ValueError, match="application failed"):
        async with agent.session() as session:
            recording = session.ctx[VideoRecording]
            recording_clock.now = 101.0
            await session.emit(
                ModelRequestedEvent(
                    request=ModelRequest(messages=()),
                    model=ModelInfo(name="test"),
                    request_id="pending",
                )
            )
            recording_clock.now = 110.0
            raise ValueError("application failed")
    assert recording.result.path.exists()
    assert len(edits) == 1
    # An unfinished LLM interval is projected through the end of the capture.
    assert edits[0][1] == ((Span(0, 1),),)
    assert recording.result.original_duration == 10
    assert recording.result.duration == 1
    tab.cdp.page.stop_screen_recording.assert_awaited_once()


@pytest.mark.parametrize("elapsed", [0.0, 0.016, 2.0])
async def test_session_with_only_waits_retains_a_final_view(
    tmp_path, monkeypatch, recording_clock, elapsed
):
    edits = []
    _install_editor(monkeypatch, edits)
    monkeypatch.setattr(recording_module, "kept_spans", lambda *_args, **_kwargs: ())
    tab = _tab("first", [])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            _BrowserService(SimpleNamespace(active_tab=tab), []),
            VideoRecording(tmp_path),
        ],
    )
    async with agent.session() as session:
        recording = session.ctx[VideoRecording]
        recording_clock.now += elapsed
    assert recording.result.original_duration == pytest.approx(elapsed)
    assert recording.result.duration == pytest.approx(1 / 30)
    (window,) = edits[0][1][0]
    assert window.start == pytest.approx(max(0, elapsed - 1 / 30))
    assert window.end == pytest.approx(max(elapsed, 1 / 30))
    tab.cdp.page.stop_screen_recording.assert_awaited_once()


async def test_missing_ffmpeg_fails_before_starting_recording(tmp_path, monkeypatch):
    monkeypatch.setattr(recording_module.shutil, "which", lambda _: None)
    tab = _tab("first", [])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            _BrowserService(SimpleNamespace(active_tab=tab), []),
            VideoRecording(tmp_path),
        ],
    )
    with pytest.raises(ExceptionGroup) as failure:
        async with agent.session():
            pytest.fail("Session should not open")
    assert failure.value.subgroup(BrowserError) is not None
    assert "FFmpeg" in str(failure.value.exceptions[0])
    tab.cdp.page.start_screen_recording.assert_not_awaited()
    assert not list(tmp_path.iterdir())


class _BrowserService(Plugin):
    events = BROWSER_EVENTS

    def __init__(self, browser, calls):
        super().__init__()
        self.browser = browser
        self.calls = calls

    async def setup(self, ctx: Context):
        ctx.provide(Browser, self.browser)
        ctx.effect(lambda: self.calls.append("browser-close"))


@pytest.fixture(name="recording_clock")
def _recording_clock(monkeypatch):
    clock = SimpleNamespace(now=100.0)

    def started(**fields):
        return ActivityStartedEvent(**fields, at=clock.now)

    # Keep native captures and Activity receipts on the same explicit timeline.
    monkeypatch.setattr(capture_module, "monotonic", lambda: clock.now)
    monkeypatch.setattr(activity_module, "ActivityStartedEvent", started)
    return clock


def _interval(kind, start, end):
    return ActivityFinishedEvent(
        interval_id="interval",
        kind=kind,
        cause_id="cause",
        started_at=start,
        at=end,
        outcome=ActivityOutcome.COMPLETED,
    )


def _tab(name, calls):
    async def start(**_options):
        calls.append(f"start-{name}")
        return SimpleNamespace(stream=f"stream-{name}")

    async def stop():
        calls.append(f"stop-{name}")
        return SimpleNamespace(stream=f"stream-{name}")

    return SimpleNamespace(
        id=name,
        cdp=SimpleNamespace(
            page=SimpleNamespace(
                start_screen_recording=AsyncMock(side_effect=start),
                stop_screen_recording=AsyncMock(side_effect=stop),
            ),
            io=SimpleNamespace(
                read=AsyncMock(
                    return_value=SimpleNamespace(
                        data="native",
                        base64_encoded=False,
                        eof=True,
                    )
                ),
                close=AsyncMock(),
            ),
        ),
    )


def _install_editor(monkeypatch, edits):
    async def edit(segments, spans, *, directory, **_options):
        edits.append((segments, spans))
        path = directory / "video.mp4"
        path.write_bytes(b"edited")
        return RecordingResult(
            path,
            tuple(s.path for s in segments),
            sum(s.ended_at - s.started_at for s in segments),
            sum(w.end - w.start for windows in spans for w in windows),
        )

    monkeypatch.setattr(recording_module.shutil, "which", lambda _: "ffmpeg")
    monkeypatch.setattr(recording_module, "edit_video", edit)
