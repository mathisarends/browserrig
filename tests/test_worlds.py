from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify.exceptions import CDPCommandError

from browserrig.browser import Frame
from browserrig.browser.worlds import Worlds
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
