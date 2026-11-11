from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import ActionContext, BrowserCoordination, Runtime


async def test_runtime_state_is_owned_by_each_session():
    agent = Agent(model=ScriptedModel([]), plugins=[Runtime()])
    async with agent.session() as first, agent.session() as second:
        first_actions, second_actions = (
            first.scope[ActionContext],
            second.scope[ActionContext],
        )
        with first_actions.activate("first"):
            assert second_actions.action_id == ""
        async with first.scope[BrowserCoordination].exclusive():
            assert not second.scope[BrowserCoordination].busy
    assert first_actions.action_id == second_actions.action_id == ""
