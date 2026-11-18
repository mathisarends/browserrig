import pytest
from harnessed import Agent as HarnessedAgent
from harnessed import ToolCall
from harnessed.errors import PluginConflict
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel

from browserrig import (
    Actions,
    Agent,
    MultiTab,
    NavigationTools,
    PointerTools,
    SingleTab,
    TabPolicy,
    TabTools,
    Targeting,
)
from tests.fakes import FakeServices


@pytest.mark.parametrize("mode, multiple", [(SingleTab, False), (MultiTab, True)])
async def test_tab_mode_controls_tools_and_prompt(mode, multiple):
    recipe = mode()
    agent = Agent(model=ScriptedModel([]), plugins=[recipe])
    selected = [
        item for item in agent.plugins if isinstance(item, (SingleTab, MultiTab))
    ]
    assert selected == [recipe]
    model = ScriptedModel(["Done"])
    async with _agent(recipe, model=model).session() as session:
        assert session.scope[TabPolicy].multiple is multiple
        names = set(session.tools)
        assert (
            {"list_tabs", "open_tab", "close_tab", "switch_tab"} <= names
        ) is multiple
        prompt = await session.prompt.render()
        assert ("new_tab" in prompt) is multiple
        assert ("This session uses one browser tab" in prompt) is not multiple
        result = await session.run("Inspect browser tools")
        assert result.text == "Done"
        offered = {tool.name: tool for tool in model.requests[0].tools}
        for name in ("navigate", "click", "click_at"):
            definition = session.tools[name]
            assert definition == offered[name]
            properties = definition.parameters["properties"]
            assert ("new_tab" in properties) is multiple
            if multiple:
                assert properties["new_tab"]["default"] is False
        if not multiple:
            result = await session.scope[ToolRegistry].execute(
                ToolCall("open_tab", {"url": "https://example.com"})
            )
            assert result.is_error and "disabled" in result.text


def test_explicit_tab_modes_conflict():
    with pytest.raises(PluginConflict, match="browserrig.tabs"):
        Agent(model=ScriptedModel([]), plugins=[SingleTab(), MultiTab()])


async def test_default_mode_is_multi_tab_and_policies_are_activation_local():
    defaults = Agent(model=ScriptedModel([]))
    assert sum(isinstance(plugin, MultiTab) for plugin in defaults.plugins) == 1
    agent = _agent(MultiTab())
    async with agent.session() as first, agent.session() as second:
        assert first.scope[TabPolicy].multiple and second.scope[TabPolicy].multiple
        assert first.scope[TabPolicy] is not second.scope[TabPolicy]


@pytest.mark.parametrize("name", ["navigate", "click", "click_at"])
@pytest.mark.parametrize("new_tab", [True, False])
async def test_single_tab_rejects_explicit_new_tab_before_input(name, new_tab):
    agent = _agent(SingleTab())
    arguments = {
        "navigate": {"url": "https://example.com"},
        "click": {"ref": "missing"},
        "click_at": {"x": 10, "y": 10},
    }[name]
    async with agent.session() as session:
        result = await session.scope[ToolRegistry].execute(
            ToolCall(name, {**arguments, "new_tab": new_tab})
        )
        assert result.is_error and "Disabled tool parameters" in result.text
        services = session.scope[FakeServices]
        assert "new_tab" in result.text and not services.events


def _agent(mode, *, model=None):
    return HarnessedAgent(
        model=ScriptedModel([]) if model is None else model,
        plugins=[
            FakeServices(),
            mode,
            Actions(),
            Targeting(),
            NavigationTools(),
            PointerTools(),
            TabTools(),
        ],
    )
