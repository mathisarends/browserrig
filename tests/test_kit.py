import pytest
from harnessed import (
    Agent,
    Instructions,
    Kit,
    KitPromptPolicy,
    Plugin,
    PluginOrder,
    PromptFormat,
    SystemPrompt,
)
from harnessed.errors import ConfigError, PluginConflict
from harnessed.plugins import PromptRenderer
from harnessed.testing import ScriptedModel

import browserrig
from browserrig import (
    Chrome,
    DomCapture,
    Done,
    FileSystemOptions,
    FileTools,
    Launch,
    Observe,
    browser_kit,
    browser_plugins,
)
from tests.fakes import FakeChrome


async def test_flat_plugins_omit_nested_kit_prompts_and_keep_explicit_prompt():
    extension = Kit("extension", [], prompt=SystemPrompt("Kit-only guidance."))
    explicit = PromptRenderer(
        SystemPrompt.from_plugins("Application guidance.", order=PluginOrder.AS_LISTED)
    )
    plugins = browser_plugins(
        extension, explicit, FakeChrome({}), without=(Chrome, FileTools)
    )
    agent = Agent(model=ScriptedModel([]), plugins=plugins)
    async with agent.session() as session:
        rendered = await session.prompt.render()
    assert "Application guidance." in rendered
    assert "Kit-only guidance." not in rendered
    assert rendered.count("Each observation starts") == 1
    assert extension.prompt is not None


def test_resolved_browser_kit_retains_replacements_and_removal_provenance():
    observe = Observe(capture=DomCapture(marks=False))
    kit = Kit("application", [browser_kit().without(FileTools), observe])
    resolved = kit.resolve(prompt=KitPromptPolicy.OMIT)
    assert observe in resolved.plugins
    assert not any(
        isinstance(item, (FileTools, PromptRenderer)) for item in resolved.plugins
    )
    selected = next(
        item for item in resolved.description.plugins if item.name == "Observe"
    )
    assert selected.kit_path == ("application",)
    assert selected.replaces[0].kit_path == ("application", "browserrig")
    assert resolved.description.removed[0].plugin.name == "FileTools"


def test_facade_reports_kit_origins_replacements_and_exclusions_without_resources(
    tmp_path,
):
    files = FileSystemOptions(directory=tmp_path / "files")
    observe = Observe(capture=DomCapture(marks=False))
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        browser=Launch(files=files),
        plugins=[observe],
        without=(FileTools,),
    )
    description = agent.describe()
    selected = next(item for item in description.plugins if item.name == "Observe")
    assert selected.kit_path == ()
    assert len(selected.replaces) == 1
    assert selected.replaces[0].kit_path == ("browserrig",)
    assert {item.plugin.name for item in description.removed} == {
        "FileTools",
    }
    assert not files.directory.exists()


async def test_nested_kit_instructions_follow_overrides_and_exclusions():
    browser = browser_kit().without(Chrome, FileTools)
    observe = Observe(capture=DomCapture(max_text_chars=1000, marks=False))
    application = Kit("application", [browser, observe])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[application, FakeChrome({})],
        instructions="Before.",
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
        assert rendered.startswith("Before.")
        assert rendered.count("Each observation starts") == 1
        assert "bounded page-text excerpt" in rendered
        assert "labeled with its ref" not in rendered
        assert "The file system observation identifies" not in rendered
    selected = next(item for item in agent.describe().plugins if item.name == "Observe")
    assert selected.kit_path == ("application",)
    assert selected.replaces[0].kit_path == ("application", "browserrig")


def test_sibling_kits_require_a_direct_slot_override():
    browser = browser_kit()
    custom = Kit("custom", [Observe()])
    with pytest.raises(PluginConflict, match="browserrig.observation"):
        browserrig.Agent(model=ScriptedModel([]), plugins=[custom])
    selected = Observe(capture=DomCapture(marks=False))
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[browser, custom, selected],
    )
    assert [plugin for plugin in agent.plugins if isinstance(plugin, Observe)] == [
        selected
    ]


@pytest.mark.parametrize("instructions", [None, "Custom role."])
async def test_facade_collects_browser_and_extension_instructions(
    instructions,
):
    class Extension(Plugin):
        def instructions(self) -> SystemPrompt:
            return SystemPrompt("Extension guidance.")

    agent = browserrig.Agent(
        model=ScriptedModel([]),
        instructions=instructions,
        plugins=[FakeChrome({}), Extension()],
        without=(Chrome,),
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
        assert rendered.count("Each observation starts") == 1
        assert rendered.count("Extension guidance.") == 1
        assert rendered.index("Each observation starts") < rendered.index(
            "Extension guidance."
        )
        if instructions is not None:
            assert rendered.startswith(instructions)


@pytest.mark.parametrize("completion_last", [False, True])
async def test_facade_renders_complete_blocks_in_plugin_list_order(completion_last):
    class Extension(Plugin):
        def instructions(self) -> SystemPrompt:
            return SystemPrompt(
                Instructions(title="Extension", text="Extension guidance.")
            )

    plugins = [FakeChrome({}), Extension()]
    plugins.insert(len(plugins) if completion_last else 0, Done())

    agent = browserrig.Agent(
        model=ScriptedModel([]),
        instructions="Custom role.",
        plugins=plugins,
        without=(Chrome,),
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
    headings = [line for line in rendered.splitlines() if line.startswith("## ")]
    assert rendered.startswith("Custom role.\n\n## Browser observations")
    assert headings == [
        "## Browser observations",
        "## Element references",
        "## Browser content and action results",
        "## Browser image history",
        "## Screenshot coordinates",
        "## Browser action chains",
        "## Workspace and downloads",
        *(
            ["## Extension", "## Explicit task completion"]
            if completion_last
            else ["## Explicit task completion", "## Extension"]
        ),
    ]


async def test_kit_prompt_follows_removals_and_replacements():
    browser = browser_kit().without(Chrome, FileTools)
    observe = Observe(capture=DomCapture(marks=False))
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[browser, observe, FakeChrome({})],
        instructions="Role.",
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
    assert rendered.count("Each observation starts") == 1
    assert "labeled with its ref" not in rendered
    assert "The file system observation identifies" not in rendered
    assert (
        rendered.index("Screenshots belong to")
        < rendered.index("Coordinates are pixels")
        < rendered.index("Combine actions only")
    )


def test_facade_requires_explicit_collection_in_an_agent_prompt():
    with pytest.raises(ConfigError, match="SystemPrompt.from_plugins"):
        browserrig.Agent(model=ScriptedModel([]), prompt=SystemPrompt("Custom role."))


async def test_explicit_prompt_overrides_kit_format_and_keeps_caller_text_first():
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        instructions="Caller role.",
        prompt=SystemPrompt.from_plugins(
            "Fixed guidance.",
            None,
            order=PluginOrder.AS_LISTED,
            format=PromptFormat.XML,
        ),
        plugins=[None, FakeChrome({}), None],
        without=(Chrome,),
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
    assert rendered.index("Caller role.") < rendered.index("Fixed guidance.")
    assert rendered.index("Fixed guidance.") < rendered.index("Each observation starts")
    assert '<section title="Browser observations">' in rendered
    assert "## Browser observations" not in rendered


async def test_instruction_providers_only_run_for_selected_recipes_once_per_agent():
    calls = []

    class CustomObserve(Observe):
        def instructions(self) -> SystemPrompt:
            calls.append(self)
            return SystemPrompt("Custom observation guidance.")

    removed = CustomObserve()
    selected = CustomObserve()
    kit = Kit("application", [browser_kit().without(Chrome), removed])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[kit, selected, FakeChrome({})],
    )
    assert calls == [selected]
    for _ in range(2):
        async with agent.session() as session:
            rendered = await session.prompt.render()
            assert rendered.count("Custom observation guidance.") == 1
            assert "Each observation starts" not in rendered
    assert calls == [selected]
