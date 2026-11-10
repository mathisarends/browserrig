import pytest
from harnessed import (
    Agent,
    Instructions,
    Plugin,
    PluginPack,
    PluginPackPromptPolicy,
    PromptFormat,
    SystemPrompt,
)
from harnessed.errors import PluginConflict
from harnessed.plugins import PromptRenderer
from harnessed.testing import ScriptedModel

import browserrig
from browserrig import (
    BrowserPerception,
    Chrome,
    DomCapture,
    Done,
    Files,
    FileTools,
    LocalWorkspace,
    browser_pack,
    browser_plugins,
)
from browserrig.tools import FormTools
from tests.fakes import FakeChrome


async def test_flat_plugins_omit_nested_pack_prompts_and_keep_explicit_prompt():
    extension = PluginPack(
        "extension", [], prompt=SystemPrompt("PluginPack-only guidance.")
    )
    explicit = PromptRenderer(
        SystemPrompt.from_plugins(
            "Application guidance.",
        )
    )
    plugins = browser_plugins(
        extension, explicit, FakeChrome({}), without=(Chrome, FileTools)
    )
    agent = Agent(model=ScriptedModel([]), plugins=plugins)
    async with agent.session() as session:
        rendered = await session.prompt.render()
    assert "Application guidance." in rendered
    assert "PluginPack-only guidance." not in rendered
    assert rendered.count("Each observation starts") == 1
    assert extension.prompt is not None


def test_resolved_browser_pack_retains_replacements_and_removal_provenance():
    observe = BrowserPerception(capture=DomCapture(marks=False))
    pack = PluginPack("application", [browser_pack().without(FileTools), observe])
    resolved = pack.resolve(prompt=PluginPackPromptPolicy.OMIT)
    assert observe in resolved.plugins
    assert not any(
        isinstance(item, (FileTools, PromptRenderer)) for item in resolved.plugins
    )
    selected = next(
        item
        for item in resolved.description.plugins
        if item.name == "BrowserPerception"
    )
    assert selected.pack_path == ("application",)
    assert selected.replaces[0].pack_path == ("application", "browserrig")
    assert resolved.description.removed[0].plugin.name == "FileTools"


def test_facade_reports_kit_origins_replacements_and_exclusions_without_resources(
    tmp_path,
):
    workspace = LocalWorkspace(tmp_path / "files")
    observe = BrowserPerception(capture=DomCapture(marks=False))
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        browser=Chrome.launch(),
        plugins=[observe, Files(workspace)],
        without=(FileTools,),
    )
    description = agent.describe()
    selected = next(
        item for item in description.plugins if item.name == "BrowserPerception"
    )
    assert selected.pack_path == ()
    assert len(selected.replaces) == 1
    assert selected.replaces[0].pack_path == ("browserrig",)
    assert {item.plugin.name for item in description.removed} == {
        "FileTools",
    }
    assert not workspace.directory.exists()


async def test_nested_pack_instructions_follow_overrides_and_exclusions():
    browser = browser_pack().without(Chrome, FileTools)
    observe = BrowserPerception(capture=DomCapture(max_text_chars=1000, marks=False))
    application = PluginPack("application", [browser, observe])
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
    selected = next(
        item for item in agent.describe().plugins if item.name == "BrowserPerception"
    )
    assert selected.pack_path == ("application",)
    assert selected.replaces[0].pack_path == ("application", "browserrig")


def test_sibling_kits_require_a_direct_slot_override():
    browser = browser_pack()
    custom = PluginPack("custom", [BrowserPerception()])
    with pytest.raises(PluginConflict, match="browserrig.observation"):
        browserrig.Agent(model=ScriptedModel([]), plugins=[custom])
    selected = BrowserPerception(capture=DomCapture(marks=False))
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[browser, custom, selected],
    )
    assert [
        plugin for plugin in agent.plugins if isinstance(plugin, BrowserPerception)
    ] == [selected]


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
        "## Browser navigation and web search",
        "## Workspace and downloads",
        "## Task working memory",
        *(
            ["## Extension", "## Explicit task completion"]
            if completion_last
            else ["## Explicit task completion", "## Extension"]
        ),
    ]


async def test_pack_prompt_follows_removals_and_replacements():
    browser = browser_pack().without(Chrome, FileTools, FormTools)
    observe = BrowserPerception(capture=DomCapture(marks=False))
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
    assert "Form filling" not in rendered
    assert (
        rendered.index("Screenshots belong to")
        < rendered.index("Coordinates are pixels")
        < rendered.index("Browser action chains")
    )


async def test_explicit_document_omits_plugin_blocks_and_reports_them():
    agent = browserrig.Agent(
        model=ScriptedModel([]), prompt=SystemPrompt("Custom role.")
    )
    rendered = await agent.prompt.render()
    assert "Custom role." in rendered
    assert "Each observation starts" not in rendered
    assert "BrowserPerception" in str(agent.prompt)


async def test_explicit_prompt_overrides_kit_format_and_keeps_caller_text_first():
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        instructions="Caller role.",
        prompt=SystemPrompt.from_plugins(
            "Fixed guidance.",
            None,
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

    class CustomPerception(BrowserPerception):
        def instructions(self) -> SystemPrompt:
            calls.append(self)
            return SystemPrompt("Custom observation guidance.")

    removed = CustomPerception()
    selected = CustomPerception()
    pack = PluginPack("application", [browser_pack().without(Chrome), removed])
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[pack, selected, FakeChrome({})],
    )
    assert calls == [selected]
    for _ in range(2):
        async with agent.session() as session:
            rendered = await session.prompt.render()
            assert rendered.count("Custom observation guidance.") == 1
            assert "Each observation starts" not in rendered
    assert calls == [selected]
