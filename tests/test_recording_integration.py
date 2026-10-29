import asyncio
import json
import shutil

import pytest
from harnessed import Agent, PolicyDecision
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import LaunchBrowser, RecordingOptions, browser_plugins
from browserrig.events import RecordingFailedEvent, RecordingStartedEvent

pytestmark = pytest.mark.integration


async def test_native_recording_writes_container_and_activity_manifest(site, tmp_path):
    agent = Agent(
        model=ScriptedModel([call("wait", seconds=0.4), "Recorded"]),
        plugins=[
            *browser_plugins(
                LaunchBrowser(url=site),
                recording=RecordingOptions(directory=tmp_path, required=True),
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Observe this page")
    assert result.text == "Recorded"
    assert any(isinstance(event, RecordingStartedEvent) for event in result.events)
    assert not any(isinstance(event, RecordingFailedEvent) for event in result.events)
    manifests = list(tmp_path.glob("*/manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text())
    assert manifest["segments"]
    segment = manifest["segments"][0]
    video = manifests[0].parent / segment["path"]
    assert video.stat().st_size == segment["size"] > 100
    assert segment["ended_at"] > segment["started_at"]
    assert any(interval["kind"] == "llm" for interval in manifest["activity"])
    assert manifest["inference_only"]
    if ffprobe := shutil.which("ffprobe"):
        process = await asyncio.create_subprocess_exec(
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(video),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        media = json.loads(stdout)
        assert float(media["format"]["duration"]) >= 0.3
        assert any(
            stream["codec_type"] == "video" and stream["width"] > 0 for stream in media["streams"]
        )
