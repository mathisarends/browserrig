import subprocess
import sys

from harnessed import Agent, Plugin, PolicyDecision, SystemSection
from harnessed.plugins import Approvals, Compaction, ContextState
from harnessed.plugins.filesystem import FilesystemTools
from harnessed.plugins.shell import ShellTools
from harnessed.testing import ScriptedModel

from browserrig import (
    BrowserAgent,
    Chrome,
    FileSystemOptions,
    LaunchBrowser,
    Observe,
    Readiness,
    ReadinessOptions,
    Screenshots,
    ScreenshotTrigger,
    WindowRatio,
)
from browserrig.tools import (
    DomTools,
    FileTools,
    JavaScriptTools,
    PointerTools,
    UploadTools,
)


def test_facade_configures_resources_without_opening_them_and_accepts_extra_plugins(
    tmp_path,
):
    class Extension(Plugin):
        usage = SystemSection(
            title="Custom extension", text="Use the custom extension."
        )

    options = LaunchBrowser(url="https://example.com", headless=False)
    readiness = ReadinessOptions(quiet_ms=123)
    file_system = FileSystemOptions(directory=tmp_path / "files")
    approvals = Approvals(default=PolicyDecision.DENY)
    extension = Extension()
    agent = BrowserAgent(
        model=ScriptedModel(["ok"]),
        browser=options,
        observe=Observe(screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP)),
        readiness=readiness,
        file_system=file_system,
        compaction=None,
        approvals=approvals,
        system_prompt="Custom instructions.",
        plugins=iter([extension]),
    )
    assert isinstance(agent, Agent)
    assert (
        next(item for item in agent.plugins if isinstance(item, Chrome)).options
        == options
    )
    assert (
        next(item for item in agent.plugins if isinstance(item, Readiness)).options
        == readiness
    )
    assert (
        next(item for item in agent.plugins if isinstance(item, Chrome)).file_system
        == file_system
    )
    assert extension in agent.plugins
    assert [item for item in agent.plugins if isinstance(item, Approvals)] == [
        approvals
    ]
    assert not any(isinstance(item, Compaction) for item in agent.plugins)
    assert not file_system.directory.exists()


def test_facade_mounts_dom_and_coordinate_tool_capabilities():
    agent = BrowserAgent(model=ScriptedModel(["ok"]))
    for plugin in (PointerTools, JavaScriptTools):
        assert sum(isinstance(item, plugin) for item in agent.plugins) == 1
    for plugin in (DomTools, UploadTools):
        assert any(isinstance(item, plugin) for item in agent.plugins)
    assert sum(isinstance(item, FileTools) for item in agent.plugins) == 1


def test_facade_compacts_by_window_ratio_and_keeps_approval_defaults():
    agent = BrowserAgent(model=ScriptedModel(["ok"]))
    assert not any(
        isinstance(item, (ShellTools, FilesystemTools)) for item in agent.plugins
    )
    (compaction,) = [item for item in agent.plugins if isinstance(item, Compaction)]
    assert compaction.config.trigger == WindowRatio(0.8, fallback_tokens=100_000)
    assert next(
        item for item in agent.plugins if isinstance(item, Approvals)
    ).default is (PolicyDecision.ASK)


def test_window_ratio_uses_the_token_fallback_only_without_a_known_window():
    trigger = WindowRatio(0.8, fallback_tokens=1000)

    def state(tokens, window):
        return ContextState(
            input_tokens=tokens,
            reserve_tokens=0,
            context_window=window,
            turns_since_compaction=0,
        )

    assert [trigger(state(900, None)), trigger(state(1000, None))] == [False, True]
    assert [trigger(state(1500, 2000)), trigger(state(1600, 2000))] == [False, True]


def test_facade_import_and_scripted_model_do_not_require_provider_sdks():
    script = (
        "import sys; "
        "from browserrig import BrowserAgent; "
        "from harnessed.testing import ScriptedModel; "
        "BrowserAgent(model=ScriptedModel(['ok'])); "
        "assert 'pydantic_ai' not in sys.modules; "
        "assert 'openai' not in sys.modules; "
        "assert 'anthropic' not in sys.modules; "
        "assert 'mcp' not in sys.modules; "
        "assert not any(name.startswith('opentelemetry') for name in sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-c", script], check=True, capture_output=True, text=True
    )
