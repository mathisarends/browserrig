import asyncio
from dataclasses import dataclass
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Plugin, PolicyDecision, ToolResult, ToolStatus
from harnessed.events import ToolCallFinishedEvent, ToolExecutionFinishedEvent
from harnessed.kernel import needs
from harnessed.models import ImagePart, ImageReference, TextPart
from harnessed.plugins import Approvals
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel, call

from browserrig.core import ActionKind, BrowserError, browser_tool
from browserrig.events import ActionFailedEvent, ActionFinishedEvent
from browserrig.tools import Actions, DialogTools
from tests.fakes import FakeServices, mounted


@pytest.mark.parametrize("status", [ToolStatus.OK, ToolStatus.TIMEOUT])
async def test_automatic_actions_preserve_rich_results_and_error_status(status):
    picture = ImagePart("data:image/png;base64,aW1hZ2U=")
    original = ToolResult(
        (TextPart("Result"), picture),
        status=status,
        exit_code=124 if status is ToolStatus.TIMEOUT else None,
    )
    agent = _agent(original, call(_ResultTools.input))
    async with agent.session() as session:
        services = session.scope[FakeServices]
        result = await session.run("Run the input")
    reply = next(
        e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)
    )
    receipt = next(
        e.result for e in result.events if isinstance(e, ToolExecutionFinishedEvent)
    )
    assert reply.status is receipt.status is status
    assert reply.exit_code == receipt.exit_code == original.exit_code
    images = [part for part in reply.content if isinstance(part, ImageReference)]
    persisted_images = [
        part for part in receipt.content if isinstance(part, ImageReference)
    ]
    assert len(images) == 1 and images == persisted_images
    assert images[0].asset.sha256 == sha256(b"image").hexdigest()
    assert images[0].detail == picture.detail
    if status is ToolStatus.OK:
        assert reply.text == receipt.text == original.text
        assert (
            len([e for e in services.events if isinstance(e, ActionFinishedEvent)]) == 1
        )
    else:
        assert reply.break_chain and receipt.break_chain
        assert "may have run" in reply.text
        assert (
            len([e for e in services.events if isinstance(e, ActionFailedEvent)]) == 1
        )


async def test_passive_tools_preserve_custom_result_conversion_without_browser_waits():
    original = _Rows(("one", "two"))
    agent = _agent(original, call(_ResultTools.data))
    async with agent.session() as session:
        services = session.scope[FakeServices]
        services.browser.active_tab.dialog = ("alert", "Blocked page")
        async with services.coordination.exclusive():
            assert await session.scope[_ResultTools].data() is original
            result = await asyncio.wait_for(session.run("Read the rows"), timeout=5)
    reply = next(
        e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)
    )
    assert reply.status is ToolStatus.OK and reply.text == "one|two"
    assert not services.readiness.phases
    assert not services.events


async def test_denied_input_never_enters_the_automatic_action_frame():
    agent = _agent(ToolResult("Unused"), call(_ResultTools.input), allow=False)
    async with agent.session() as session:
        services = session.scope[FakeServices]
        result = await session.run("Try the input")
    reply = next(
        e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)
    )
    assert reply.status is ToolStatus.DENIED
    assert not services.readiness.phases and not services.events


async def test_dialog_handling_bypasses_an_existing_action_lock():
    async with mounted(Actions(), _Dialogs()) as (services, scope):
        tab = services.browser.active_tab
        tab.dialog = ("alert", "Continue?")
        tab.handle_dialog = AsyncMock()
        async with services.coordination.exclusive():
            result = await asyncio.wait_for(
                scope[_Dialogs].handle_dialog(accept=True), timeout=5
            )
            assert services.coordination.busy
        tab.handle_dialog.assert_awaited_once_with(accept=True, text="")
    assert result == "Dialog handled."
    assert not services.readiness.phases and not services.events


@dataclass(frozen=True)
class _Rows:
    values: tuple[str, ...]


class _ResultTools(Plugin, needs=(Actions,), provides=True):
    _registry = needs(ToolRegistry)

    def __init__(self, value):
        super().__init__()
        self.value = value

    async def setup(self, scope):
        self._registry.result_converter(
            _Rows, lambda rows: ToolResult("|".join(rows.values)), owner=scope
        )

    @browser_tool(kind=ActionKind.JAVASCRIPT, description="Return an input receipt.")
    async def input(self):
        return self.value

    @browser_tool(
        kind=ActionKind.LIST_TABS, description="Return structured rows.", readonly=True
    )
    async def data(self):
        return self.value


class _Dialogs(DialogTools, provides=True):
    """Expose the mounted dialog tool for a direct-call lock test."""


def _agent(value, request, *, allow=True):
    return Agent(
        model=ScriptedModel([request, "Done"]),
        plugins=[
            FakeServices(),
            Actions(),
            _ResultTools(value),
            Approvals(default=PolicyDecision.ALLOW if allow else PolicyDecision.DENY),
        ],
    )


@pytest.mark.parametrize("dispatch", [False, True])
async def test_tracked_input_distinguishes_preparation_from_primary_dispatch(dispatch):
    agent = Agent(
        model=ScriptedModel([call("tracked_input", dispatch=dispatch), "Done"]),
        plugins=[
            FakeServices(),
            Actions(),
            _TrackedInput(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Run tracked input")
        services = session.scope[FakeServices]
        assert session.scope[_TrackedInput].effects == int(dispatch)
    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    (failure,) = [
        event for event in services.events if isinstance(event, ActionFailedEvent)
    ]
    assert reply.is_error and failure.dispatched is dispatch
    assert ("may have run" in reply.text) is dispatch
    assert ("not dispatched" in reply.text) is not dispatch


class _TrackedInput(Plugin, needs=(Actions,), provides=True):
    actions = needs(Actions)

    def __init__(self):
        super().__init__()
        self.effects = 0

    @browser_tool(
        kind=ActionKind.CLICK, description="Test tracked input.", dispatch_tracked=True
    )
    async def tracked_input(self, dispatch: bool):
        if not dispatch:
            raise BrowserError("Target unavailable before input")

        async def mutate():
            self.effects += 1
            raise BrowserError("Failed after mutation")

        await self.actions.dispatch(mutate)
