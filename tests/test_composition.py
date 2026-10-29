import subprocess
import sys

import pytest
from harnessed import Agent, Plugin, PolicyDecision
from harnessed.plugins import Approvals, JsonlSessions, MemorySessions
from harnessed.testing import ScriptedModel

from browserrig import (
    BrowserAgent,
    CanvasMode,
    Chrome,
    DomMode,
    FileSystemOptions,
    LaunchBrowser,
    Readiness,
    ReadinessOptions,
    Recording,
    RecordingOptions,
)
from browserrig.tools import FileTools, FormTools, InteractionTools, PointerTools, UploadTools


def test_facade_configures_resources_without_opening_them_and_accepts_extra_plugins(tmp_path):
    class Extension(Plugin):
        guidance = "Use the custom extension."

    options = LaunchBrowser(url="https://example.com", headless=False)
    readiness = ReadinessOptions(quiet_ms=123)
    recording = RecordingOptions(directory=tmp_path / "recordings")
    file_system = FileSystemOptions(directory=tmp_path / "files")
    approvals = Approvals(default=PolicyDecision.DENY)
    extension = Extension()
    agent = BrowserAgent(
        model=ScriptedModel(["ok"]),
        browser=options,
        mode=DomMode(screenshots=True),
        readiness=readiness,
        recording=recording,
        file_system=file_system,
        session_directory=tmp_path / "sessions",
        approvals=approvals,
        instructions="Custom instructions.",
        plugins=iter([extension]),
    )
    assert isinstance(agent, Agent)
    assert next(item for item in agent.plugins if isinstance(item, Chrome)).options == options
    assert next(item for item in agent.plugins if isinstance(item, Readiness)).options == readiness
    assert next(item for item in agent.plugins if isinstance(item, Recording)).options == recording
    assert (
        next(item for item in agent.plugins if isinstance(item, Chrome)).file_system == file_system
    )
    assert extension in agent.plugins
    assert [item for item in agent.plugins if isinstance(item, Approvals)] == [approvals]
    assert sum(isinstance(item, JsonlSessions) for item in agent.plugins) == 1
    assert not any(isinstance(item, MemorySessions) for item in agent.plugins)
    assert not (tmp_path / "sessions").exists()
    assert not recording.directory.exists()
    assert not file_system.directory.exists()


@pytest.mark.parametrize(
    "mode,interaction", [(DomMode(), InteractionTools), (CanvasMode(), PointerTools)]
)
def test_facade_keeps_dom_and_canvas_tool_sets_distinct(mode, interaction):
    agent = BrowserAgent(model=ScriptedModel(["ok"]), mode=mode)
    assert sum(isinstance(item, interaction) for item in agent.plugins) == 1
    has_forms = any(isinstance(item, FormTools) for item in agent.plugins)
    has_uploads = any(isinstance(item, UploadTools) for item in agent.plugins)
    assert has_forms == has_uploads == isinstance(mode, DomMode)
    assert sum(isinstance(item, FileTools) for item in agent.plugins) == 1
    assert next(item for item in agent.plugins if isinstance(item, Readiness)).mode == mode


def test_facade_retains_native_memory_storage_and_approval_defaults():
    agent = BrowserAgent(model=ScriptedModel(["ok"]))
    assert sum(isinstance(item, MemorySessions) for item in agent.plugins) == 1
    assert not any(isinstance(item, JsonlSessions) for item in agent.plugins)
    assert next(item for item in agent.plugins if isinstance(item, Approvals)).default is (
        PolicyDecision.ASK
    )


def test_facade_import_and_scripted_model_do_not_require_provider_sdks():
    script = (
        "import sys; "
        "from browserrig import BrowserAgent; "
        "from harnessed.testing import ScriptedModel; "
        "BrowserAgent(model=ScriptedModel(['ok'])); "
        "assert 'pydantic_ai' not in sys.modules; "
        "assert 'openai' not in sys.modules; "
        "assert 'anthropic' not in sys.modules; "
        "assert not any(name.startswith('opentelemetry') for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
