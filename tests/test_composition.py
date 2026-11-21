import subprocess
import sys

import pytest
from harnessed import Agent, Approvals, Plugin, SystemPrompt
from harnessed.context import ContextState
from harnessed.errors import PluginConflict
from harnessed.models import Decision
from harnessed.plugins.filesystem import Filesystem
from harnessed.plugins.shell import Shell
from harnessed.prompts import Instructions
from harnessed.testing import ScriptedModel

import browserrig
from browserrig import (
    BrowserFileTools,
    BrowserPerception,
    Choreography,
    ChoreographyOverlay,
    Chrome,
    Files,
    FileTools,
    FormTools,
    InputPacing,
    JavaScriptTools,
    LocalWorkspace,
    PageReadiness,
    PointerTools,
    ReadinessOptions,
    ReferencePointerTools,
    Screenshots,
    ScreenshotTrigger,
    Secret,
    Secrets,
    TabStrip,
    TaskMemory,
    WorkspaceTools,
)
from browserrig.input import Instant
from browserrig.observation import (  # smelt: ignore[IMP004] -- facade identity
    # Compare the two facade exports, not a name with itself.
    BrowserPerception as PerceptionExport,
)


def test_browser_perception_is_exported_without_legacy_top_level_names():
    assert BrowserPerception is PerceptionExport
    assert BrowserPerception.__name__ == "BrowserPerception"
    assert not {"Observe", "Launch", "Connect"}.intersection(browserrig.__all__)
    assert not any(
        hasattr(browserrig, name) for name in ("Observe", "Launch", "Connect")
    )


def test_facade_configures_resources_without_opening_them_and_accepts_extra_plugins(
    tmp_path,
):
    class Extension(Plugin):
        def instructions(self) -> SystemPrompt:
            return SystemPrompt(
                Instructions(title="Custom extension", text="Use the custom extension.")
            )

    workspace = LocalWorkspace(tmp_path / "files")
    browser = Chrome.launch(url="https://example.com", headless=False)
    files = Files(workspace)
    readiness = ReadinessOptions(quiet_ms=123)
    approvals = Approvals(default=Decision.DENY)
    extension = Extension()
    agent = browserrig.Agent(
        model=ScriptedModel(["ok"]),
        browser=browser,
        instructions="Custom instructions.",
        plugins=[
            Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
            PageReadiness(options=readiness),
            files,
            extension,
        ],
        approvals=approvals,
        without=(TaskMemory,),
    )
    assert isinstance(agent, Agent)
    assert next(item for item in agent.plugins if isinstance(item, Chrome)) is browser
    assert (
        next(item for item in agent.plugins if isinstance(item, PageReadiness)).options
        == readiness
    )
    assert extension in agent.plugins
    assert [item for item in agent.plugins if isinstance(item, Files)] == [files]
    assert agent.approvals is approvals
    assert agent.context.compaction is None
    assert not workspace.directory.exists()


def test_facade_mounts_every_tool_group_once():
    agent = browserrig.Agent(model=ScriptedModel(["ok"]))
    for plugin in (PointerTools, ReferencePointerTools, JavaScriptTools):
        assert sum(isinstance(item, plugin) for item in agent.plugins) == 1
    for plugin in (FormTools, FileTools):
        assert any(isinstance(item, plugin) for item in agent.plugins)
    assert sum(isinstance(item, FileTools) for item in agent.plugins) == 1


def test_facade_compacts_by_window_ratio_and_keeps_approval_defaults():
    agent = browserrig.Agent(model=ScriptedModel(["ok"]))
    assert not any(isinstance(item, (Shell, Filesystem)) for item in agent.plugins)
    assert agent.context.compaction is not None
    assert agent.approvals.default is Decision.ALLOW


def test_default_compaction_uses_fallback_only_without_a_known_window():
    context = browserrig.Agent(model=ScriptedModel([])).context
    assert context.compaction is not None
    trigger = context.compaction.config.trigger

    def state(tokens, window):
        return ContextState(
            input_tokens=tokens,
            reserve_tokens=0,
            context_window=window,
            turns_since_compaction=0,
        )

    assert [trigger(state(99_999, None)), trigger(state(100_000, None))] == [
        False,
        True,
    ]
    assert [trigger(state(1500, 2000)), trigger(state(1600, 2000))] == [False, True]


def test_facade_import_and_scripted_model_do_not_require_provider_sdks():
    script = (
        "import sys; "
        "from browserrig import Agent; "
        "from harnessed.testing import ScriptedModel; "
        "Agent(model=ScriptedModel(['ok'])); "
        "assert 'pydantic_ai' not in sys.modules; "
        "assert 'openai' not in sys.modules; "
        "assert 'anthropic' not in sys.modules; "
        "assert 'mcp' not in sys.modules; "
        "assert not any(name.startswith('opentelemetry') for name in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_plugins_replace_matching_defaults_in_place():
    observe = Screenshots(trigger=ScreenshotTrigger.EACH_STEP, skip_unchanged=False)
    memory = TaskMemory(warn_at=0.6)
    defaults = browserrig.Agent(model=ScriptedModel([])).plugins
    composed = browserrig.Agent(
        model=ScriptedModel([]), plugins=[memory, observe]
    ).plugins
    assert len(composed) == len(defaults)
    assert composed[_index(defaults, TaskMemory)] is memory
    assert observe in composed and memory in composed
    assert composed.index(observe) == _index(defaults, Screenshots)


def test_plugins_without_a_matching_default_are_added():
    secrets = Secrets({"pw": Secret("value", domains="example.org")})
    composed = browserrig.Agent(model=ScriptedModel([]), plugins=[secrets]).plugins
    assert composed[-1] is secrets
    assert len(composed) == len(browserrig.Agent(model=ScriptedModel([])).plugins) + 1


def test_plugin_list_rejects_none():
    with pytest.raises(TypeError, match="Expected a Plugin instance"):
        browserrig.Agent(model=ScriptedModel([]), plugins=[None])


def test_two_plugins_for_the_same_default_conflict():
    with pytest.raises(PluginConflict, match="BrowserPerception"):
        browserrig.Agent(
            model=ScriptedModel([]), plugins=[BrowserPerception(), BrowserPerception()]
        )


@pytest.mark.parametrize("group", [WorkspaceTools, BrowserFileTools])
def test_one_file_tool_group_replaces_the_combined_default_in_place(group):
    defaults = browserrig.Agent(model=ScriptedModel([])).plugins
    tools = group()
    composed = browserrig.Agent(model=ScriptedModel([]), plugins=[tools]).plugins
    assert len(composed) == len(defaults)
    assert composed[_index(defaults, FileTools)] is tools
    assert not any(isinstance(plugin, FileTools) for plugin in composed)


def test_without_matches_each_file_tool_group_exactly():
    assert not isinstance(FileTools(), (WorkspaceTools, BrowserFileTools))
    with pytest.raises(ValueError, match="no defaults matching: BrowserFileTools"):
        browserrig.Agent(model=ScriptedModel([]), without=(BrowserFileTools,))


def test_two_file_tool_groups_conflict():
    with pytest.raises(PluginConflict, match="browserrig.file-tools"):
        browserrig.Agent(
            model=ScriptedModel([]), plugins=[WorkspaceTools(), BrowserFileTools()]
        )


def test_configured_pacing_and_choreography_replace_their_defaults_in_place():
    defaults = browserrig.Agent(model=ScriptedModel([])).plugins
    pacing, choreography = InputPacing(Instant()), Choreography()
    composed = browserrig.Agent(
        model=ScriptedModel([]), plugins=[choreography, pacing]
    ).plugins
    assert len(composed) == len(defaults)
    assert composed[_index(defaults, InputPacing)] is pacing
    assert composed[_index(defaults, Choreography)] is choreography


def test_without_drops_defaults_and_rejects_types_that_are_not_defaults():
    composed = browserrig.Agent(
        model=ScriptedModel([]),
        without=(Choreography, ChoreographyOverlay, TabStrip, TaskMemory),
    ).plugins
    assert not any(
        isinstance(plugin, (Choreography, ChoreographyOverlay, TabStrip, TaskMemory))
        for plugin in composed
    )
    with pytest.raises(ValueError, match="has no defaults matching: Secrets"):
        browserrig.Agent(model=ScriptedModel([]), without=(Secrets,))


def _index(plugins, kind):
    return next(i for i, plugin in enumerate(plugins) if isinstance(plugin, kind))
