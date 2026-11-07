from harnessed import Plugin, ToolResult, tool
from harnessed.testing import ScriptedModel, call

from browserrig import Secrets
from browserrig.core import ActionKind, BrowserToolMetadata
from tests.secrets.test_secrets import Leaky, _agent, _secrets


class _AliasedJavaScript(Plugin):
    @tool(
        description="Evaluate page JavaScript.",
        metadata=(BrowserToolMetadata(kind=ActionKind.JAVASCRIPT),),
    )
    async def evaluate_page(self) -> ToolResult:
        return ToolResult("listener installed")


async def test_aliased_javascript_is_blocked_before_secret_entry():
    model = ScriptedModel([call("evaluate_page"), "done"])
    agent, _ = _agent(_secrets(), model=model, plugins=[_AliasedJavaScript()])
    await agent.run("go", max_steps=3)
    replies = repr(model.requests[-1].messages)
    assert "JavaScript execution is unavailable" in replies
    assert "listener installed" not in replies


async def test_empty_secret_configuration_allows_javascript():
    model = ScriptedModel([call("execute_javascript", code="1"), "done"])
    agent, _ = _agent(Secrets({}), model=model, plugins=[Leaky()])
    await agent.run("go", max_steps=3)
    assert "ran 1" in repr(model.requests[-1].messages)
