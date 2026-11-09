import inspect
from functools import partial, wraps

import pytest

from browserrig.core import ActionKind, browser_tool


def test_browser_tool_rejects_synchronous_callbacks_at_declaration_time():
    def click() -> str:
        raise AssertionError("Rejected callbacks must never execute")

    with pytest.raises(TypeError, match="requires an async function"):
        browser_tool(kind=ActionKind.CLICK, description="Click")(click)


async def test_browser_tool_accepts_partials_and_marked_wrappers_of_async_callbacks():
    async def click(label: str) -> str:
        return label

    def logged(callback):
        @wraps(callback)
        def wrapper(*args, **kwargs):
            return callback(*args, **kwargs)

        return inspect.markcoroutinefunction(wrapper)

    declare = browser_tool(kind=ActionKind.CLICK, description="Click")
    assert await declare(partial(click, "partial"))() == "partial"
    assert await declare(logged(click))("marked") == "marked"
