import json

import pytest
from cdpify.exceptions import CDPCommandError
from harnessed import Agent, PolicyDecision
from harnessed.models import ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Browser, ChromeBrowser, Launch, browser_plugins
from browserrig.core import BrowserError
from browserrig.events import ActionFailedEvent, ActionFinishedEvent
from browserrig.kinds import ActionKind
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_agent_javascript_shell_retains_main_world_state_awaits_and_reports_errors(
    site,
):
    url = site
    model = ScriptedModel(
        [
            call("execute_javascript", code="const shellCounter = 40; shellCounter"),
            call(
                "execute_javascript",
                code="const shellCounter = await Promise.resolve(shellCounter + 2); "
                "document.title = 'From JavaScript'; "
                "window.shellMarker = 'main'; ({value: shellCounter, marker: shellMarker})",
            ),
            call(
                "execute_javascript",
                code="window.shellRuns = (window.shellRuns || 0) + 1; "
                "throw new Error('shell failure')",
            ),
            call("execute_javascript", code="window.shellRuns"),
            "Done",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(browser=Launch(url=url)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Run JavaScript", max_steps=5)
        assert result.text == "Done"
        replies = [
            msg for msg in model.requests[-1].messages if isinstance(msg, ToolMessage)
        ]
        assert [reply.is_error for reply in replies] == [False, False, True, False]
        assert replies[0].text == "JavaScript result:\n40"
        assert json.loads(replies[1].text.split("\n", 1)[1]) == {
            "value": 42,
            "marker": "main",
        }
        assert "Error: shell failure" in replies[2].text
        assert replies[3].text == "JavaScript result:\n1"
        tab = session.ctx[Browser].active_tab
        assert await evaluate(tab, "document.title") == "From JavaScript"
        assert await evaluate(tab, "typeof window.shellMarker") == "undefined"
        finished = [
            event for event in result.events if isinstance(event, ActionFinishedEvent)
        ]
        assert len(finished) == 3
        assert all(event.kind == ActionKind.JAVASCRIPT for event in finished)
        failed = [
            event for event in result.events if isinstance(event, ActionFailedEvent)
        ]
        assert len(failed) == 1 and failed[0].dispatched


async def test_runtime_shell_values_and_execution_deadlines_in_chrome(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        for code, expected in (
            ("null", "null"),
            ("undefined", "undefined"),
            ("NaN", "NaN"),
            ("Infinity", "Infinity"),
            ("-Infinity", "-Infinity"),
            ("-0", "-0"),
            ("42n", "42n"),
            ("await Promise.resolve([1, 2])", "[1, 2]"),
        ):
            assert await tab.evaluate(code) == expected
        with pytest.raises(BrowserError, match="result cannot be returned by value"):
            await tab.evaluate(
                "window.nonserializableRuns = (window.nonserializableRuns || 0) + 1; "
                "Symbol('shell')"
            )
        assert await tab.evaluate("window.nonserializableRuns") == "1"
        with pytest.raises(BrowserError, match="JavaScript failed: SyntaxError"):
            await tab.evaluate("const = ;")
        with pytest.raises(BrowserError, match="JavaScript failed:.*rejected"):
            await tab.evaluate("await Promise.reject(new Error('rejected'))")
        with pytest.raises(BrowserError, match="JavaScript timed out"):
            await tab.evaluate("await new Promise(() => {})", timeout=0.1)
        assert await tab.evaluate("1 + 1") == "2"
        with pytest.raises(
            (BrowserError, CDPCommandError), match="terminated|timed out"
        ):
            await tab.evaluate("while (true) {}", timeout=0.1)
        assert await tab.evaluate("2 + 2") == "4"
