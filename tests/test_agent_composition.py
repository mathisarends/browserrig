import pytest
from harnessed import Plugin, SystemPrompt
from harnessed.prompts import Instructions, PromptFormat
from harnessed.testing import ScriptedModel

import browserrig
from browserrig import (
    BrowserPerception,
    Chrome,
    Done,
    Files,
    FileTools,
    FormTools,
    LocalWorkspace,
    Screenshots,
    ScreenshotTrigger,
    SetOfMarks,
)
from tests.fakes import FakeChrome


def test_facade_describes_selected_plugins_without_resources(
    tmp_path,
):
    workspace = LocalWorkspace(tmp_path / "files")
    observe = BrowserPerception()
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
    assert selected.slot == "browserrig.observation"
    assert "FileTools" not in {item.name for item in description.plugins}
    assert description.model is not None
    assert "AgentLoop" in description.loop
    assert not workspace.directory.exists()


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
        "## Browser content and action results",
        "## Screenshot coordinates",
        "## Browser screenshots",
        "## Page elements",
        "## Element references",
        "## Screenshot marks",
        "## Browser action chains",
        "## Multiple browser tabs",
        "## Browser navigation and web search",
        "## Workspace and downloads",
        "## Task working memory",
        *(
            ["## Extension", "## Explicit task completion"]
            if completion_last
            else ["## Explicit task completion", "## Extension"]
        ),
    ]


async def test_facade_prompt_follows_removals_and_replacements():
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        plugins=[Screenshots(trigger=ScreenshotTrigger.EACH_STEP), FakeChrome({})],
        without=(Chrome, FileTools, FormTools, SetOfMarks),
        instructions="Role.",
    )
    async with agent.session() as session:
        rendered = await session.prompt.render()
    assert rendered.count("Each observation starts") == 1
    assert "labeled with its ref" not in rendered
    assert "The file system observation identifies" not in rendered
    assert "Form filling" not in rendered
    assert (
        rendered.index("Screenshot coordinates")
        < rendered.index("Browser screenshots")
        < rendered.index("Browser action chains")
    )


async def test_explicit_document_omits_plugin_blocks_and_reports_them():
    agent = browserrig.Agent(
        model=ScriptedModel([]), instructions=SystemPrompt("Custom role.")
    )
    rendered = await agent.prompt.render()
    assert "Custom role." in rendered
    assert "Each observation starts" not in rendered
    assert "BrowserPerception" in str(agent.prompt)


async def test_explicit_prompt_overrides_default_format_and_keeps_caller_text_first():
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        instructions=SystemPrompt.from_plugins(
            "Caller role.",
            "Fixed guidance.",
            format=PromptFormat.XML,
        ),
        plugins=[FakeChrome({})],
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

    selected = CustomPerception()
    agent = browserrig.Agent(
        model=ScriptedModel([]),
        plugins=[selected, FakeChrome({})],
        without=(Chrome,),
    )
    assert calls == [selected]
    for _ in range(2):
        async with agent.session() as session:
            rendered = await session.prompt.render()
            assert rendered.count("Custom observation guidance.") == 1
            assert "Each observation starts" not in rendered
    assert calls == [selected]
