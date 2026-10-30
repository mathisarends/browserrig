import pytest
from harnessed import Agent, PolicyDecision
from harnessed.models import ToolReply
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import LaunchBrowser, browser_plugins
from browserrig.events import ActionFailedEvent, ActionFinishedEvent

pytestmark = pytest.mark.integration


async def test_agent_go_forward_reports_success_and_missing_or_replaced_history(site):
    model = ScriptedModel(
        [
            call("go_forward"),
            call("navigate", url=site + "/other"),
            call("go_back"),
            call("go_forward"),
            call("go_forward"),
            call("go_back"),
            call("navigate", url=site + "/canvas"),
            call("go_forward"),
            "Done",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(LaunchBrowser(url=site)),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Navigate through history", max_steps=9)
    assert result.text == "Done"
    replies = [msg for msg in model.requests[-1].messages if isinstance(msg, ToolReply)]
    assert [reply.is_error for reply in replies] == [
        True,
        False,
        False,
        False,
        True,
        False,
        False,
        True,
    ]
    assert replies[3].text == "Navigated forward."
    for index in (0, 4, 7):
        assert "Cannot go forward: no next history entry" in replies[index].text
        assert "may have run" not in replies[index].text
    navigations = [event for event in result.events if isinstance(event, ActionFinishedEvent)]
    assert [event.after_url for event in navigations] == [
        site + "/other",
        site + "/",
        site + "/other",
        site + "/",
        site + "/canvas",
    ]
    failures = [event for event in result.events if isinstance(event, ActionFailedEvent)]
    assert len(failures) == 3 and all(not event.dispatched for event in failures)
