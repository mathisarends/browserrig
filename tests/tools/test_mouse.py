import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import call as mock_call

import pytest
from harnessed import Agent, PolicyDecision, ToolStatus
from harnessed.events import ToolCallFinishedEvent, ToolExecutionFinishedEvent
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig.core import BrowserError, ElementPoint
from browserrig.events import ActionFailedEvent, ActionFinishedEvent, ActionStartedEvent
from browserrig.tools import Actions, PointerTools, TabTools
from tests.fakes import FakeServices


@pytest.mark.parametrize("arguments", [{"x": 40, "y": 30}, {"ref": "button"}])
async def test_move_mouse_runs_as_an_action_and_stops_the_native_chain(arguments):
    move = call(PointerTools.move_mouse, **arguments)
    trailing = call(TabTools.list_tabs)
    batch = [
        ModelChunk(tool_call=tool_call)
        for response in (move, trailing)
        for tool_call in response.message.tool_calls
    ]
    async with _pointer_session([batch, "Done"]) as (session, services, moved):
        action_ids = []
        moved.side_effect = lambda _point: action_ids.append(
            services.browser.input.action_id
        )
        result = await session.run("Hover the target")
        with pytest.raises(RuntimeError, match="executing action tool"):
            await session.scope[Actions].element_point(ref="button")

    moved.assert_awaited_once()
    assert moved.await_args.args[0].x == 40
    assert moved.await_args.args[0].y == 30
    if "ref" in arguments:
        assert services.observe.element.await_args_list == [
            mock_call(services.browser.active_tab, "button"),
            mock_call(services.browser.active_tab, "button"),
        ]
    replies = [e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)]
    assert replies[0].status is ToolStatus.OK and replies[0].break_chain
    assert "Cursor moved" in replies[0].text
    assert replies[1].status is ToolStatus.SKIPPED
    receipts = [
        e.result for e in result.events if isinstance(e, ToolExecutionFinishedEvent)
    ]
    assert len(receipts) == 1 and receipts[0].break_chain
    started = [e for e in services.events if isinstance(e, ActionStartedEvent)]
    finished = [e for e in services.events if isinstance(e, ActionFinishedEvent)]
    assert len(started) == len(finished) == 1
    assert action_ids == [started[0].action_id] == [finished[0].action_id]
    assert not services.coordination.busy


@pytest.mark.parametrize(
    "arguments",
    [{}, {"x": 1}, {"ref": "button", "x": 1, "y": 2}],
)
async def test_move_mouse_rejects_ambiguous_arguments_without_input(arguments):
    async with _pointer_session(
        [call(PointerTools.move_mouse, **arguments), "Done"]
    ) as (session, services, moved):
        result = await session.run("Hover")

    moved.assert_not_awaited()
    reply = next(
        e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)
    )
    assert reply.status is ToolStatus.ERROR and reply.break_chain
    assert "Provide" in reply.text
    assert len([e for e in services.events if isinstance(e, ActionFailedEvent)]) == 1
    assert not any(isinstance(e, ActionFinishedEvent) for e in services.events)
    assert not services.coordination.busy


async def test_move_mouse_keeps_input_failure_and_releases_the_action_context():
    responses = [
        call(PointerTools.move_mouse, x=40, y=30),
        call(PointerTools.move_mouse, ref="button"),
        "Done",
    ]
    async with _pointer_session(responses) as (session, services, moved):
        moved.side_effect = [BrowserError("Input connection lost"), None]
        result = await session.run("Hover")

    assert moved.await_count == 2
    replies = [e.result for e in result.events if isinstance(e, ToolCallFinishedEvent)]
    assert replies[0].status is ToolStatus.ERROR and replies[0].break_chain
    assert "Input connection lost" in replies[0].text
    assert "may have run" in replies[0].text
    assert replies[1].status is ToolStatus.OK
    assert len([e for e in services.events if isinstance(e, ActionFailedEvent)]) == 1
    assert len([e for e in services.events if isinstance(e, ActionFinishedEvent)]) == 1
    assert not services.coordination.busy


async def test_cancelled_move_mouse_releases_control_and_records_uncertain_input():
    async with _pointer_session([call(PointerTools.move_mouse, x=40, y=30)]) as (
        session,
        services,
        moved,
    ):
        entered = asyncio.Event()

        async def pause(_point):
            entered.set()
            await asyncio.Event().wait()

        moved.side_effect = pause
        task = asyncio.create_task(session.run("Hover"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    moved.assert_awaited_once()
    failed = [e for e in services.events if isinstance(e, ActionFailedEvent)]
    assert len(failed) == 1 and failed[0].cancelled and failed[0].dispatched
    assert not any(isinstance(e, ActionFinishedEvent) for e in services.events)
    assert not services.coordination.busy


async def test_direct_tool_calls_keep_their_owner_session_and_release_context():
    async with _pointer_session(["Done"]) as (first, first_services, first_move):
        async with _pointer_session(["Done"]) as (second, second_services, second_move):
            await first.scope[_PointerTools].move_mouse(ref="button")
            first_move.assert_awaited_once()
            second_move.assert_not_awaited()
            await second.scope[_PointerTools].move_mouse(ref="button")
            second_move.assert_awaited_once()
            for session in (first, second):
                with pytest.raises(RuntimeError, match="executing action tool"):
                    _ = session.scope[Actions].tab
        await first.scope[_PointerTools].move_mouse(x=40, y=30)
        assert first_move.await_count == 2

    assert (
        len([e for e in first_services.events if isinstance(e, ActionFinishedEvent)])
        == 2
    )
    assert (
        len([e for e in second_services.events if isinstance(e, ActionFinishedEvent)])
        == 1
    )


async def test_finished_tool_context_cannot_be_reused_by_an_inherited_task():
    release = asyncio.Event()
    inherited = []
    async with _pointer_session(["Done"]) as (session, _services, moved):
        actions = session.scope[Actions]

        async def read_after_completion():
            await release.wait()
            return actions.tab

        def start_child(_point):
            inherited.append(asyncio.create_task(read_after_completion()))

        moved.side_effect = start_child
        try:
            await session.scope[_PointerTools].move_mouse(x=40, y=30)
        finally:
            release.set()
        assert len(inherited) == 1
        with pytest.raises(RuntimeError, match="executing action tool"):
            await asyncio.wait_for(inherited[0], timeout=5)
    moved.assert_awaited_once()


@asynccontextmanager
async def _pointer_session(responses):
    agent = Agent(
        model=ScriptedModel(responses),
        plugins=[
            FakeServices(),
            Actions(),
            _PointerTools(),
            TabTools(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    async with agent.session() as session:
        services = session.scope[FakeServices]
        moved = services.browser.input.mouse.move_to = AsyncMock()
        services.observe.coordinate_source = lambda: SimpleNamespace(
            geometry=None, width=800, height=600
        )
        services.observe.element = AsyncMock(
            return_value=SimpleNamespace(
                element=SimpleNamespace(bounds=None),
                locate=AsyncMock(return_value=ElementPoint(x=40, y=30)),
            )
        )
        yield session, services, moved


class _PointerTools(PointerTools, provides=True):
    """Expose the mounted tools to verify direct calls across concurrent sessions."""
