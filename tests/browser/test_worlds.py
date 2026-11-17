from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify import CDPCommandError

from browserrig.browser import Frame
from browserrig.browser.worlds import (  # smelt: ignore[SMT107] -- test seam
    # Test isolated-world lifecycle independently of Chrome transport.
    Worlds,
)
from browserrig.scripts import RESET


async def test_world_is_shared_across_frame_discoveries_and_bound_to_document():
    frame, cdp = _frame()
    assert await frame.context() == await replace(frame).context() == 1
    assert await replace(frame, document_id="next-document").context() == 2
    assert cdp.page.create_isolated_world.await_count == 2


async def test_destroyed_context_is_invalidated_selectively():
    frame, _cdp = _frame()
    await frame.context()
    frame.worlds.invalidate(session_id="another-session", context_id=1)
    assert await frame.context() == 1
    frame.worlds.invalidate(session_id="session", context_id=1)
    assert await frame.context() == 2


async def test_missing_context_recreates_world_and_retries_once():
    frame, cdp = _frame()
    result = cdp.runtime.call_function_on.return_value
    missing = CDPCommandError(
        "Runtime.callFunctionOn", -32000, "Cannot find context with specified id"
    )
    cdp.runtime.call_function_on.side_effect = [missing, result]
    await frame.run(RESET)
    assert cdp.runtime.call_function_on.await_count == 2
    assert cdp.page.create_isolated_world.await_count == 2


async def test_other_cdp_failures_are_not_retried():
    frame, cdp = _frame()
    cdp.runtime.call_function_on.side_effect = CDPCommandError(
        "Runtime.callFunctionOn", -32000, "Execution context was destroyed"
    )
    with pytest.raises(CDPCommandError):
        await frame.run(RESET)
    assert cdp.runtime.call_function_on.await_count == 1


@pytest.mark.parametrize(
    "selectors, expired",
    [
        pytest.param({}, {"first", "second", "third"}, id="all"),
        pytest.param({"session_id": "one"}, {"first", "second"}, id="session"),
        pytest.param({"frame_id": "main"}, {"first", "third"}, id="frame"),
        pytest.param({"context_id": 2}, {"second"}, id="context"),
        pytest.param({"context_id": 0}, set(), id="unmatched-context"),
        pytest.param(
            {"session_id": "one", "frame_id": "main"}, {"first"}, id="session-frame"
        ),
        pytest.param(
            {"session_id": "two", "context_id": 1}, set(), id="mismatched-session"
        ),
        pytest.param(
            {"frame_id": "child", "context_id": 3}, set(), id="mismatched-frame"
        ),
    ],
)
async def test_world_invalidation_combines_all_provided_selectors(selectors, expired):
    worlds = Worlds()
    identifiers = iter(range(1, 10))
    create = AsyncMock(
        side_effect=lambda **_: SimpleNamespace(execution_context_id=next(identifiers))
    )
    one = SimpleNamespace(
        session_id="one", page=SimpleNamespace(create_isolated_world=create)
    )
    two = SimpleNamespace(
        session_id="two", page=SimpleNamespace(create_isolated_world=create)
    )
    targets = {"first": (one, "main"), "second": (one, "child"), "third": (two, "main")}
    original = {
        name: await worlds.context(cdp, frame, "document")
        for name, (cdp, frame) in targets.items()
    }
    worlds.invalidate(**selectors)
    current = {
        name: await worlds.context(cdp, frame, "document")
        for name, (cdp, frame) in targets.items()
    }
    assert {name for name in targets if current[name] != original[name]} == expired


def _frame():
    cdp = SimpleNamespace(
        session_id="session",
        page=SimpleNamespace(
            create_isolated_world=AsyncMock(
                side_effect=[
                    SimpleNamespace(execution_context_id=1),
                    SimpleNamespace(execution_context_id=2),
                ]
            )
        ),
        runtime=SimpleNamespace(
            call_function_on=AsyncMock(
                return_value=SimpleNamespace(
                    exception_details=None, result=SimpleNamespace(value=None)
                )
            )
        ),
    )
    return Frame("frame", cdp, document_id="document", worlds=Worlds()), cdp
