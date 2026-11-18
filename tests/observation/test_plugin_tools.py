import pytest
from harnessed import Agent, ToolCall
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel

from browserrig import (
    Actions,
    BrowserPerception,
    DomScrollTools,
    DomTypingTools,
    Files,
    FormTools,
    KeyboardTools,
    PageReadiness,
    PageSearchTools,
    PointerTools,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTools,
    Targeting,
)
from tests.fakes import FakeChrome


@pytest.mark.parametrize(
    "extension,expected",
    [
        (None, set()),
        (DomTypingTools(), {"type_text"}),
        (DomScrollTools(), {"scroll_page", "scroll_element"}),
        (FormTools(), {"select_option", "select_options", "set_date"}),
        (ScreenshotTools(), {"screenshot"}),
        (PageSearchTools(), {"search_page"}),
    ],
)
async def test_tools_are_exposed_only_by_the_selected_capability_plugin(
    extension, expected
):
    model = ScriptedModel([])
    plugins = [
        FakeChrome({}),
        PageReadiness(),
        BrowserPerception(screenshots=Screenshots()),
        Actions(),
        Targeting(),
        KeyboardTools(),
        PointerTools(),
        Files(),
    ]
    if extension is not None:
        plugins.append(extension)
    agent = Agent(model=model, plugins=plugins)
    async with agent.session() as session:
        names = {tool.name for tool in session.scope[ToolRegistry].definitions}
        if isinstance(extension, ScreenshotTools):
            info = session.scope[ToolRegistry].plan(ToolCall("screenshot", {})).tool
            assert set(info.definition.parameters["properties"]) == {"region"}
            assert not info.definition.parameters.get("required")
        assert (
            names
            == {"send_keys", "click", "click_at", "move_mouse", "drag", "drag_at"}
            | expected
        )
    assert not model.requests


@pytest.mark.parametrize("pixels", [False, True])
async def test_model_tools_follow_the_configured_capture(pixels):
    perception = (
        BrowserPerception(
            capture=ScreenshotCapture(), text=None, screenshots=Screenshots()
        )
        if pixels
        else BrowserPerception()
    )
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            FakeChrome({}),
            PageReadiness(),
            perception,
            Actions(),
            Targeting(),
            DomScrollTools(),
            DomTypingTools(),
            FormTools(),
            ScreenshotTools(),
        ],
    )
    async with agent.session() as session:
        names = {tool.name for tool in session.scope[ToolRegistry].definitions}
        assert ("screenshot" in names) is pixels
        assert {
            "scroll_page",
            "scroll_element",
            "type_text",
            "select_options",
        } & names == (
            set()
            if pixels
            else {"scroll_page", "scroll_element", "type_text", "select_options"}
        )
