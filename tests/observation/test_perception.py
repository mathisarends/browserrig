import pytest
from harnessed import Agent
from harnessed.errors import PluginDependencyError
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel

from browserrig import (
    Actions,
    BrowserPerception,
    DomPerception,
    DomScrollTools,
    DomTypingTools,
    Files,
    FormTools,
    KeyboardTools,
    PageExtractionTools,
    PointerTools,
    Readiness,
    ScreenshotTools,
    TextContext,
)
from browserrig.observation import DomCapture, DomRenderer
from tests.fakes import FakeChrome


@pytest.mark.parametrize(
    "extension,expected",
    [
        (None, set()),
        (DomTypingTools(), {"type_text"}),
        (DomScrollTools(), {"scroll_page", "scroll_element"}),
        (FormTools(), {"select_option", "select_options", "set_date"}),
        (ScreenshotTools(), {"screenshot"}),
        (PageExtractionTools(), {"extract_content"}),
    ],
)
async def test_tools_are_exposed_only_by_the_selected_capability_plugin(
    extension, expected
):
    model = ScriptedModel([])
    plugins = [
        FakeChrome({}),
        Readiness(),
        DomPerception(),
        TextContext(),
        Actions(),
        KeyboardTools(),
        PointerTools(),
        Files(),
    ]
    if extension is not None:
        plugins.append(extension)
    agent = Agent(model=model, plugins=plugins)
    async with agent.session() as session:
        names = {tool.name for tool in session.scope[ToolRegistry].definitions}
        assert (
            names
            == {"send_keys", "click", "click_at", "move_mouse", "drag", "drag_at"}
            | expected
        )
    assert not model.requests


async def test_page_extraction_without_a_workspace_fails_before_model_use():
    model = ScriptedModel([])
    agent = Agent(
        model=model, plugins=[FakeChrome({}), Readiness(), PageExtractionTools()]
    )
    with pytest.raises(
        PluginDependencyError, match="PageExtractionTools requires FileSystem"
    ):
        await agent.run("Read the page")
    assert not model.requests


async def test_generic_perception_does_not_satisfy_dom_tool_dependencies():
    model = ScriptedModel([])
    agent = Agent(
        model=model,
        plugins=[
            FakeChrome({}),
            Readiness(),
            BrowserPerception(capture=DomCapture(), renderer=DomRenderer()),
            Actions(),
            DomTypingTools(),
        ],
    )
    with pytest.raises(
        PluginDependencyError, match="DomTypingTools requires DomElements"
    ):
        await agent.run("Type in a field")
    assert not model.requests
