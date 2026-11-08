import pytest
from harnessed import Agent, Plugin, PolicyDecision, tool
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import AllowedDomains
from browserrig.core import ActionKind, BrowserToolMetadata


class _ScriptTools(Plugin):
    def __init__(self, executed):
        super().__init__()
        self.executed = executed

    @tool(description="Execute JavaScript.")
    async def execute_javascript(self, code: str) -> str:
        self.executed.append(code)
        return "Script executed"

    @tool(
        description="Evaluate JavaScript under an alias.",
        metadata=(BrowserToolMetadata(kind=ActionKind.JAVASCRIPT),),
    )
    async def evaluate_page(self, code: str) -> str:
        self.executed.append(code)
        return "Script executed"


@pytest.mark.parametrize("name", ["execute_javascript", "evaluate_page"])
@pytest.mark.parametrize("domains", [(), ("example.com",)])
async def test_javascript_tools_and_aliases_are_blocked_without_execution(
    name, domains
):
    executed = []
    model = ScriptedModel([call(name, code="fetch('https://denied.test')"), "done"])
    agent = Agent(
        model=model,
        plugins=[
            _ScriptTools(executed),
            AllowedDomains(domains),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    await agent.run("go", max_steps=3)
    assert executed == []
    assert (
        "JavaScript execution is unavailable while allowed domains are configured."
        in repr(model.requests[-1].messages)
    )


async def test_omitting_plugin_keeps_javascript_available():
    executed = []
    model = ScriptedModel([call("execute_javascript", code="1+1"), "done"])
    await Agent(
        model=model,
        plugins=[_ScriptTools(executed), Approvals(default=PolicyDecision.ALLOW)],
    ).run("go", max_steps=3)
    assert executed == ["1+1"]
    assert "Script executed" in repr(model.requests[-1].messages)
