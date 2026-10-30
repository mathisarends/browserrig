import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import (
    Agent,
    Plugin,
    PolicyDecision,
    ToolChain,
    ToolError,
    ToolResult,
    ToolStatus,
    hook,
)
from harnessed.events import ToolCallFinishedEvent, ToolExecutionFinishedEvent
from harnessed.hooks import ReviewToolResult
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig.core.kinds import ActionKind
from browserrig.events import ActionFailedEvent, ActionFinishedEvent, PageState
from browserrig.observation.changes import decision_change
from browserrig.observation.models import Element, Snapshot
from browserrig.tools import Actions, BrowserToolMetadata, browser_tool
from browserrig.tools.execution import Effect


def _element(**values):
    return Element.model_validate(
        {
            "ref": "first-ref",
            "frame_id": "frame",
            "backend_id": 10,
            "role": "textbox",
            "name": "Email",
            "tag": "input",
            **values,
        }
    )


def test_probe_changes_ignore_values_cosmetic_text_ref_renaming_and_prepared_scroll():
    before = _snapshot(elements=(_element(in_viewport=False),))
    after = _snapshot(
        id="after",
        title="Cosmetic title",
        text="A ticking clock",
        scroll_y=200,
        fingerprint="different",
        elements=(_element().model_copy(update={"ref": "new-ref", "value": "typed"}),),
    )
    assert decision_change(before, after) == ""


@pytest.mark.parametrize("previous", [None, {"covered": True}, {"disabled": True}])
def test_new_or_newly_available_controls_interrupt(previous):
    before = _snapshot(elements=() if previous is None else (_element(**previous),))
    assert "interactive" in decision_change(before, _snapshot())


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://example.org/#next"},
        {"document_id": "other"},
        {"tab_id": "other"},
        {"modal": {"role": "dialog", "name": "Choose"}},
        {"alerts": ("Invalid entry",)},
        {"elements": (_element(expanded=True),)},
    ],
)
def test_new_decisions_interrupt(changes):
    assert decision_change(_snapshot(), _snapshot(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"in_viewport": False},
        {"covered": True},
        {"disabled": True},
    ],
)
def test_unavailable_new_controls_do_not_interrupt(changes):
    assert not decision_change(_snapshot(elements=()), _snapshot(elements=(_element(**changes),)))


class _Tools(Plugin):
    # Exercise Browserrig's result review inside the native executor without starting Chrome.
    _review_browser_result = Actions._review_browser_result  # pylint: disable=protected-access
    _execute_browser_result = Actions._execute_browser_result  # pylint: disable=protected-access

    def __init__(self, executed):
        super().__init__()
        self.executed = executed

    @browser_tool(description="Fill a field.", chainable=True, kind=ActionKind.TYPE)
    async def fill(self, value: str) -> str:
        self.executed.append(value)
        if value == "error":
            raise ToolError("Field disappeared")
        return "Entered"

    @browser_tool(description="Change browser context.", kind=ActionKind.SWITCH_TAB)
    async def change(self) -> str:
        self.executed.append("change")
        return "Changed"

    @browser_tool(description="Reveal suggestions.", kind=ActionKind.SELECT, chainable=True)
    async def suggest(self) -> ToolResult:
        self.executed.append("suggest")
        return ToolResult("Suggestions appeared", break_chain=True)


@pytest.mark.parametrize(
    "boundary,expected",
    [
        (call(_Tools.change), ["first", "change"]),
        (call(_Tools.suggest), ["first", "suggest"]),
        (call(_Tools.fill, value="error"), ["first", "error"]),
    ],
)
async def test_native_chain_skips_trailing_calls_after_boundary_or_failure(boundary, expected):
    executed = []
    model = ScriptedModel(
        [
            _batch(call(_Tools.fill, value="first"), boundary, call(_Tools.fill, value="last")),
            "Done",
        ]
    )
    agent = Agent(model=model, plugins=[_Tools(executed), Approvals(default=PolicyDecision.ALLOW)])
    result = await agent.run("Fill the form")
    replies = [e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)]
    assert executed == expected
    assert replies[1].break_chain
    assert replies[2].status is ToolStatus.SKIPPED
    receipts = [e.result for e in result.events if isinstance(e, ToolExecutionFinishedEvent)]
    assert len(receipts) == 2 and receipts[1].break_chain
    assert result.completed and result.text == "Done"


async def test_denied_boundary_does_not_discard_unrelated_followup():
    executed = []
    model = ScriptedModel([_batch(call(_Tools.change), call(_Tools.fill, value="allowed")), "Done"])
    agent = Agent(
        model=model,
        plugins=[
            _Tools(executed),
            Approvals(default=PolicyDecision.ALLOW, deny=["change"]),
        ],
    )
    result = await agent.run("Fill a field")
    replies = [e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)]
    assert replies[0].status is ToolStatus.DENIED and not replies[0].break_chain
    assert replies[1].status is ToolStatus.OK
    assert executed == ["allowed"]


async def test_browser_metadata_is_captured_for_review_without_reaching_the_model():
    executed, registrations = [], []

    class Inspect(Plugin):
        @hook(ReviewToolResult)
        async def review(self, event: ReviewToolResult, next_):
            registrations.append(event.tool)
            return await next_()

    model = ScriptedModel([call(_Tools.fill, value="value"), "Done"])
    await Agent(
        model=model,
        plugins=[
            _Tools(executed),
            Inspect(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    ).run("Fill")
    info = registrations[0]
    assert info.metadata.get(BrowserToolMetadata) == BrowserToolMetadata(ActionKind.TYPE, True)
    assert info.chain is ToolChain.CONTINUE and not info.parallel
    assert "BrowserToolMetadata" not in str(model.requests[0].tools)


async def test_failed_comparison_keeps_input_successful_and_breaks_the_chain():
    before = _snapshot()
    events = []
    tab = SimpleNamespace(
        id="tab",
        document_id="doc",
        url=before.url,
        closed=False,
        input=SimpleNamespace(action=lambda _: nullcontext()),
    )
    actions = SimpleNamespace(
        observe=SimpleNamespace(snapshot=before, probe=AsyncMock(side_effect=RuntimeError("lost"))),
        browser=SimpleNamespace(active_tab=tab, action_lock=asyncio.Lock()),
        _prepare=AsyncMock(
            return_value=PageState(
                url=before.url,
                document_id=before.document_id,
            )
        ),
        _settle=AsyncMock(return_value=""),
        _events=SimpleNamespace(emit=AsyncMock(side_effect=events.append)),
    )
    actions.page_change = lambda selected: Actions.page_change(actions, selected)
    result = await Actions.run(
        actions,
        kind=ActionKind.TYPE,
        operation=AsyncMock(return_value=Effect("Entered once.")),
    )
    assert result.status is ToolStatus.OK and result.break_chain
    assert "Entered once" in result.text and "could not be checked" in result.text
    assert any(isinstance(event, ActionFinishedEvent) for event in events)
    assert not any(isinstance(event, ActionFailedEvent) for event in events)


def _snapshot(**values):
    fields = {
        "id": "before",
        "tab_id": "tab",
        "document_id": "doc",
        "url": "https://example.org/",
        "title": "Form",
        "mode": "dom",
        "readiness": "ready",
        "width": 800,
        "height": 600,
        "scroll_y": 0,
        "fingerprint": "first",
        "elements": (_element(),),
    }
    return Snapshot.model_validate(fields | values)


def _batch(*responses):
    return [
        ModelChunk(tool_call=tool_call)
        for response in responses
        for tool_call in response.message.tool_calls
    ]
