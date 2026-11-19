import pytest
from harnessed import Agent, ToolCall
from harnessed.testing import ScriptedModel
from harnessed.tools import ToolRegistry

from browserrig import (
    Actions,
    BrowserPerception,
    DomCapture,
    DomScrollTools,
    DomTypingTools,
    DomUploadTools,
    Files,
    FormTools,
    KeyboardTools,
    PageReadiness,
    PageSearchTools,
    PointerTools,
    ReferencePointerTools,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTools,
    SetOfMarks,
    Targeting,
    TextObservations,
)
from tests.fakes import FakeChrome


async def test_observation_guidance_works_without_browser_tools():
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            FakeChrome({}),
            PageReadiness(),
            BrowserPerception(screenshots=Screenshots(marks=SetOfMarks())),
        ],
    )
    async with agent.session() as session:
        assert not session.scope[ToolRegistry].definitions
        prompt = await session.prompt.render()

    assert "Each observation starts" in prompt
    assert "outlined and labeled" in prompt
    assert "Refs stay valid while the element" in prompt
    assert "scroll_element" not in prompt and "scroll_page" not in prompt
    assert "type_text" not in prompt and "search_page" not in prompt
    assert "screenshot tool" not in prompt and "click_at" not in prompt


def test_marks_require_an_element_capture_for_metadata_observations():
    text = TextObservations(content="metadata")
    screenshots = Screenshots(marks=SetOfMarks())
    with pytest.raises(ValueError, match="element refs for screenshot marks"):
        BrowserPerception(text=text, screenshots=screenshots)

    capture = DomCapture()
    perception = BrowserPerception(text=text, screenshots=screenshots, capture=capture)
    assert perception.capture_strategy is capture


@pytest.mark.parametrize(
    "extension,expected",
    [
        (None, set()),
        (ReferencePointerTools(), {"click", "hover", "drag"}),
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
        assert names == {"send_keys", "click_at", "move_mouse", "drag_at"} | expected
    assert not model.requests


async def test_screenshot_only_pointer_tools_have_required_coordinates():
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[
            FakeChrome({}),
            PageReadiness(),
            BrowserPerception(
                capture=ScreenshotCapture(), text=None, screenshots=Screenshots()
            ),
            Actions(),
            PointerTools(),
        ],
    )
    async with agent.session() as session:
        assert set(session.tools) == {"click_at", "drag_at", "move_mouse"}
        parameters = session.tools["move_mouse"].parameters
        assert set(parameters["properties"]) == {"x", "y"}
        assert set(parameters["required"]) == {"x", "y"}
        assert all(
            field["type"] == "number" for field in parameters["properties"].values()
        )


@pytest.mark.parametrize("pixels", [False, True])
async def test_model_tools_follow_the_configured_capture(pixels, caplog):
    caplog.set_level("DEBUG", logger="browserrig.tools.parameters")
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
            DomUploadTools(),
            FormTools(),
            ScreenshotTools(),
        ],
    )
    async with agent.session() as session:
        names = {tool.name for tool in session.scope[ToolRegistry].definitions}
        assert ("screenshot" in names) is pixels
        assert "scroll_page" in names
        assert {
            "scroll_element",
            "type_text",
            "select_options",
        } & names == (
            set() if pixels else {"scroll_element", "type_text", "select_options"}
        )
        reported = {
            record.message.split(":", 1)[0]
            for record in caplog.records
            if record.name == "browserrig.tools.parameters"
        }
        assert reported == (
            {"DomScrollTools", "DomTypingTools", "DomUploadTools", "FormTools"}
            if pixels
            else set()
        )
