import asyncio
import json
import shutil
import subprocess

import pytest
from harnessed import Agent
from harnessed.events import AssistantMessageEvent, ModelRequestedEvent
from harnessed.models import AssistantMessage, ModelInfo, ModelRequest
from harnessed.testing import ScriptedModel

from browserrig import Activity, Browser, Chrome, VideoRecording
from browserrig.recording import capture as capture_module
from tests.javascript import evaluate

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
        reason="Recording integration requires FFmpeg and ffprobe",
    ),
]


async def test_native_recording_cuts_model_waits_across_tabs_and_closure(
    tmp_path, site
):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            Chrome.launch(url=site),
            VideoRecording(tmp_path, width=640, height=480, frame_rate=15, padding=0),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        recording = session.scope[VideoRecording]
        first = browser.active_tab
        await evaluate(first, "document.body.style.background='lime'")
        await asyncio.sleep(0.5)
        await session.emit(
            ModelRequestedEvent(
                request=ModelRequest(messages=()),
                model=ModelInfo(name="test"),
                request_id="wait",
            )
        )
        await evaluate(first, "document.body.style.background='red'")
        await asyncio.sleep(1.5)
        await evaluate(first, "document.body.style.background='lime'")
        await session.emit(
            AssistantMessageEvent(AssistantMessage("continue"), request_id="wait")
        )
        await asyncio.sleep(0.5)
        second = await browser.tabs.open(site + "/other")
        await evaluate(second, "document.body.style.background='blue'")
        await asyncio.sleep(0.5)
        await browser.tabs.close(second.id)
        assert browser.active_tab.id == first.id
        await asyncio.sleep(0.5)
    result = recording.result
    assert result is not None
    assert result.path.is_file()
    assert len(result.sources) == 3
    manifest = json.loads((result.path.parent / "timeline.json").read_text())
    assert [s["target_id"] for s in manifest] == [first.id, second.id, first.id]
    retained = sum(end - start for s in manifest for start, end in s["kept"])
    assert result.original_duration - retained >= 1.5
    # Retained intervals round outward to whole frames to preserve brief actions.
    rounding = 2 * sum(len(s["kept"]) for s in manifest) / 15
    assert result.original_duration - result.duration >= 1.5 - rounding
    info = await asyncio.to_thread(
        subprocess.run,
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(result.path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    metadata = json.loads(info.stdout)
    assert float(metadata["format"]["duration"]) == pytest.approx(
        result.duration, abs=0.3
    )
    stream = metadata["streams"][0]
    assert (stream["codec_name"], stream["width"], stream["height"]) == (
        "h264",
        640,
        480,
    )
    colors = await _video_colors(result.path)
    assert any(green > 180 and red < 60 and blue < 60 for red, green, blue in colors)
    assert any(blue > 180 and red < 60 and green < 60 for red, green, blue in colors)
    # At most a few transition frames survive either edge of the cut.
    assert (
        sum(red > 180 and green < 60 and blue < 60 for red, green, blue in colors) <= 3
    )


async def test_recording_follows_repeated_activation_of_existing_tabs(tmp_path, site):
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            Chrome.launch(url=site),
            VideoRecording(tmp_path, width=640, height=480, frame_rate=15, padding=0),
        ],
    )
    async with agent.session() as session:
        browser = session.scope[Browser]
        recording = session.scope[VideoRecording]
        first = browser.active_tab
        await evaluate(first, "document.body.style.background='lime'")
        await asyncio.sleep(0.5)
        second = await browser.tabs.open(site + "/other")
        await evaluate(second, "document.body.style.background='blue'")
        await asyncio.sleep(0.5)
        await browser.tabs.activate(first.id)
        await asyncio.sleep(0.5)
        # Reactivating the current tab must not split its ongoing capture.
        await browser.tabs.activate(first.id)
        await browser.tabs.activate(second.id)
        await asyncio.sleep(0.5)
        await browser.tabs.close(second.id)
        assert browser.active_tab.id == first.id
        await asyncio.sleep(0.5)
    result = recording.result
    assert result is not None
    assert len(result.sources) == 5
    expected = [first.id, second.id, first.id, second.id, first.id]
    manifest = json.loads((result.path.parent / "timeline.json").read_text())
    assert [s["target_id"] for s in manifest] == expected
    # Decode the final video to verify the visible tab order independently of
    # the manifest. Ignore unpainted frames at initial page load.
    visible_tabs = []
    for red, green, blue in await _video_colors(result.path):
        tab = None
        if green > 180 and red < 60 and blue < 60:
            tab = first.id
        elif blue > 180 and red < 60 and green < 60:
            tab = second.id
        if tab is not None and (not visible_tabs or visible_tabs[-1] != tab):
            visible_tabs.append(tab)
    assert visible_tabs == expected


@pytest.mark.parametrize("same_tick", [False, True])
async def test_immediate_session_exit_still_produces_a_video(
    tmp_path, monkeypatch, same_tick
):
    if same_tick:
        monkeypatch.setattr(capture_module, "monotonic", lambda: 100.0)
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            Activity(),
            Chrome.launch(),
            VideoRecording(tmp_path, width=320, height=240, frame_rate=15, padding=0),
        ],
    )
    async with agent.session() as session:
        recording = session.scope[VideoRecording]
    assert recording.result is not None
    assert recording.result.path.stat().st_size > 0
    assert recording.result.duration >= 1 / 15
    if same_tick:
        assert recording.result.original_duration == 0
    probe = await asyncio.to_thread(
        subprocess.run,
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            str(recording.result.path),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert int(probe.stdout) >= 1


async def _video_colors(path):
    decoded = await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "crop=100:100:500:300,scale=1:1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return list(zip(*[iter(decoded.stdout)] * 3, strict=True))
