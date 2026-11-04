import subprocess
import sys

import pytest
from harnessed import Agent, Instructions, Plugin, PolicyDecision, SystemPrompt
from harnessed.errors import PluginConflict
from harnessed.plugins import Approvals, Compaction, ContextState
from harnessed.plugins.filesystem import FilesystemTools
from harnessed.plugins.shell import ShellTools
from harnessed.testing import ScriptedModel

import browserrig
from browserrig import (
    BrowserPerception,
    Chrome,
    FileSystemOptions,
    ImageContext,
    InputPacing,
    InputVisualization,
    Readiness,
    ReadinessOptions,
    Screenshots,
    ScreenshotTrigger,
    Secret,
    Secrets,
    TabStrip,
    WindowRatio,
    browser_plugins,
)
from browserrig.input import Instant
from browserrig.observation import BrowserPerception as PerceptionExport
from browserrig.tools import (
    FileTools,
    FormTools,
    JavaScriptTools,
    PointerTools,
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

    file_system = FileSystemOptions(directory=tmp_path / "files")
    browser = Chrome.launch(
        url="https://example.com", headless=False, files=file_system
    )
    readiness = ReadinessOptions(quiet_ms=123)
    approvals = Approvals(default=PolicyDecision.DENY)
    extension = Extension()
    agent = browserrig.Agent(
        model=ScriptedModel(["ok"]),
        browser=browser,
        instructions="Custom instructions.",
        plugins=[
            BrowserPerception(
                screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP)
            ),
            Readiness(options=readiness),
            approvals,
            extension,
        ],
        without=(Compaction,),
    )
    assert isinstance(agent, Agent)
    assert next(item for item in agent.plugins if isinstance(item, Chrome)) is browser
    assert (
        next(item for item in agent.plugins if isinstance(item, Readiness)).options
        == readiness
    )
    assert extension in agent.plugins
    assert [item for item in agent.plugins if isinstance(item, Approvals)] == [
        approvals
    ]
    assert not any(isinstance(item, Compaction) for item in agent.plugins)
    assert not file_system.directory.exists()


def test_facade_mounts_every_tool_group_once():
    agent = browserrig.Agent(model=ScriptedModel(["ok"]))
    for plugin in (PointerTools, JavaScriptTools):
        assert sum(isinstance(item, plugin) for item in agent.plugins) == 1
    for plugin in (FormTools, FileTools):
        assert any(isinstance(item, plugin) for item in agent.plugins)
    assert sum(isinstance(item, FileTools) for item in agent.plugins) == 1


def test_facade_compacts_by_window_ratio_and_keeps_approval_defaults():
    agent = browserrig.Agent(model=ScriptedModel(["ok"]))
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
    observe = BrowserPerception(
        screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP)
    )
    images = ImageContext(skip_unchanged=False)
    compaction = Compaction(trigger=WindowRatio(0.5))
    defaults = browser_plugins()
    composed = browser_plugins(compaction, images, observe)
    assert [type(plugin) for plugin in composed] == [
        type(plugin) for plugin in defaults
    ]
    assert observe in composed and images in composed and compaction in composed
    assert composed.index(observe) == _index(defaults, BrowserPerception)
    assert composed.index(images) == _index(defaults, ImageContext)


def test_plugins_without_a_matching_default_are_added_and_none_is_skipped():
    secrets = Secrets({"pw": Secret("value", domains="example.org")})
    composed = browser_plugins(None, secrets, None)
    assert composed[-1] is secrets
    assert None not in composed
    assert len(composed) == len(browser_plugins()) + 1


def test_two_plugins_for_the_same_default_conflict():
    with pytest.raises(PluginConflict, match="BrowserPerception"):
        browser_plugins(BrowserPerception(), BrowserPerception())
    with pytest.raises(PluginConflict, match="browserrig.images"):
        browser_plugins(ImageContext(), ImageContext())


def test_configured_pacing_and_choreography_replace_their_defaults_in_place():
    defaults = browser_plugins()
    pacing, choreography = InputPacing(Instant()), InputVisualization()
    composed = browser_plugins(choreography, pacing)
    assert len(composed) == len(defaults)
    assert composed[_index(defaults, InputPacing)] is pacing
    assert composed[_index(defaults, InputVisualization)] is choreography


def test_without_drops_defaults_and_rejects_types_that_are_not_defaults():
    composed = browser_plugins(without=(InputVisualization, TabStrip, Compaction))
    assert not any(
        isinstance(plugin, (InputVisualization, TabStrip, Compaction))
        for plugin in composed
    )
    with pytest.raises(ValueError, match="contains no recipes matching: Secrets"):
        browser_plugins(without=(Secrets,))


def _index(plugins, kind):
    return next(i for i, plugin in enumerate(plugins) if isinstance(plugin, kind))
