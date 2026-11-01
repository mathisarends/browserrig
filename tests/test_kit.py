import pytest
from harnessed import Agent, Instructions, Kit, Plugin, SystemPrompt
from harnessed.errors import ConfigError, PluginConflict
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
    browser_instructions,
    browser_kit,
)
from tests.fakes import FakeChrome


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
        system_prompt=SystemPrompt("Before.", application.instructions, "After."),
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
        assert rendered.startswith("Before.") and rendered.endswith("After.")
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
        system_prompt=SystemPrompt(browser.instructions),
    )
    assert [plugin for plugin in agent.plugins if isinstance(plugin, Observe)] == [
        selected
    ]


@pytest.mark.parametrize("prompt", [None, "Custom role."])
async def test_facade_places_browser_and_extension_instructions_for_plain_prompts(
    prompt,
):
    class Extension(Plugin):
        usage = Instructions(text="Extension guidance.")

    agent = browserrig.Agent(
        model=ScriptedModel([]),
        system_prompt=prompt,
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
        if prompt is not None:
            assert rendered.startswith(prompt)


async def test_facade_renders_titled_sections_in_reading_order_with_completion_last():
    class Extension(Plugin):
        usage = Instructions(title="Extension", text="Extension guidance.")

    agent = browserrig.Agent(
        model=ScriptedModel([]),
        system_prompt="Custom role.",
        plugins=[Done(), FakeChrome({}), Extension()],
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
        "## Extension",
        "## Explicit task completion",
    ]


async def test_browser_instructions_follow_kit_removals_and_replacements():
    browser = browser_kit().without(Chrome, FileTools)
    observe = Observe(capture=DomCapture(marks=False))
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[browser, observe, FakeChrome({})],
        system_prompt=SystemPrompt("Role.", browser_instructions(browser)),
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


def test_facade_requires_explicit_placement_in_a_system_prompt():
    with pytest.raises(ConfigError, match="Unplaced system sections"):
        browserrig.Agent(
            model=ScriptedModel([]), system_prompt=SystemPrompt("Custom role.")
        )
