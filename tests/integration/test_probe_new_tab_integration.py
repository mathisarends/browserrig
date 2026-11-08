import pytest
from harnessed import PolicyDecision, ToolCall
from harnessed.models import ModelChunk, ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import Agent, Chrome
from tests.observations import all_states

pytestmark = pytest.mark.integration


async def test_probe_target_blank(site):
    stage = 0
    log = []

    async def respond(request):
        nonlocal stage
        page = all_states(request.messages)[-1]
        replies = [m for m in request.messages if isinstance(m, ToolMessage)]
        log.append(
            {
                "stage": stage,
                "tab": page["page"].get("tab"),
                "url": page["page"].get("url"),
                "reply": replies[-1].text if replies else None,
                "nudges": [m.text for m in request.messages if "nudges" in m.text][-1:],
            }
        )
        if stage == 0:
            button = [e for e in page["elements"] if e["name"] == "New tab"][0]
            call = ToolCall("click", {"ref": button["ref"]})
        elif stage == 1:
            call = ToolCall("list_tabs", {})
        else:
            yield ModelChunk(text="Done")
            return
        stage += 1
        yield ModelChunk(tool_call=call)

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
    )
    await agent.run("probe", max_steps=5)
    for entry in log:
        print(entry)
    raise AssertionError("show output")
