import inspect
from functools import partial, wraps

import pytest
from harnessed import Plugin
from harnessed.testing import mount_plugin

from browserrig.core import ActionKind, BrowserToolCall, browser_tool


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


async def test_browser_tool_bindings_isolate_activations_and_end_with_their_scope():
    calls = []

    class Tools(Plugin):
        async def setup(self, scope):
            async def record(event, next_):
                calls.append((self, event.arguments["label"]))
                return await next_()

            scope.on(BrowserToolCall, record)

        @browser_tool(kind=ActionKind.CLICK, description="Click")
        async def click(self, label: str) -> str:
            return label

    recipe = Tools()
    async with mount_plugin(recipe) as first:
        async with mount_plugin(recipe) as second:
            assert first is not second
            assert await first.click("first") == "first"
            assert await second.click("second") == "second"
        with pytest.raises(RuntimeError, match="disposed activation"):
            await second.click("unmounted")
        assert await first.click("still mounted") == "still mounted"
    with pytest.raises(RuntimeError, match="disposed activation"):
        await first.click("unmounted")
    assert calls == [(first, "first"), (second, "second"), (first, "still mounted")]
