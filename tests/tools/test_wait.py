import asyncio
from unittest.mock import AsyncMock

import pytest
from harnessed import ToolCall
from harnessed.kernel import PluginActivated
from harnessed.services import ToolRegistry

from browserrig import ActionKind, Actions, NavigationTools, WaitTools
from browserrig.tools import BrowserToolMetadata, WaitIntent
from tests.fakes import mounted


@pytest.mark.parametrize(
    "plugins, navigation, maximum, description",
    [
        (
            lambda: [WaitTools()],
            False,
            10,
            "Wait briefly for an expected asynchronous page update.",
        ),
        (
            lambda: [NavigationTools()],
            True,
            10,
            "Wait briefly for an expected asynchronous page update.",
        ),
        (
            lambda: [NavigationTools(), WaitTools(0.5, "Wait for the canvas.")],
            True,
            0.5,
            "Wait for the canvas.",
        ),
        (
            lambda: [WaitTools(0.5, "Wait for the canvas."), NavigationTools()],
            True,
            0.5,
            "Wait for the canvas.",
        ),
    ],
)
async def test_wait_registers_once_and_uses_explicit_configuration(
    plugins, navigation, maximum, description
):
    async with mounted(Actions(), *plugins()) as (_, scope):
        registry = scope[ToolRegistry]
        names = [tool.name for tool in registry.definitions]
        expected = ["wait"]
        if navigation:
            expected.extend(("navigate", "search", "go_back", "go_forward", "reload"))
        assert sorted(names) == sorted(expected)
        info = registry.plan(ToolCall("wait", {})).tool
        assert info.readonly
        metadata = info.metadata.get(BrowserToolMetadata)
        assert metadata is not None and metadata.kind is ActionKind.WAIT
        assert info.definition.description == description
        seconds = info.definition.parameters["properties"]["seconds"]
        assert seconds["minimum"] == 0
        assert seconds["maximum"] == maximum
        assert seconds["default"] == min(1, maximum)
        result = await registry.execute(ToolCall("wait", {"seconds": maximum + 1}))
        assert result.is_error and "Invalid arguments for wait" in result.text


async def test_unmounting_explicit_wait_restores_navigation_default():
    async with mounted(Actions(), NavigationTools()) as (_, scope):
        registry = scope[ToolRegistry]
        call = ToolCall("wait", {})
        default = registry.plan(call).tool.definition
        async with await scope.plugin(WaitTools(description="Wait for the canvas.")):
            await scope.settle()
            assert (
                registry.plan(call).tool.definition.description
                == "Wait for the canvas."
            )
        await scope.settle()
        assert registry.plan(call).tool.definition == default


async def test_failed_explicit_activation_restores_navigation_default():
    async with mounted(Actions(), NavigationTools()) as (_, scope):
        registry = scope[ToolRegistry]
        call = ToolCall("wait", {})
        default = registry.plan(call).tool.definition
        configured = WaitTools(description="Wait for the canvas.")

        def reject_explicit_wait(event: PluginActivated) -> None:
            if WaitTools in event.handle.spec.provides:
                raise RuntimeError("Explicit wait activation failed")

        remove_listener = scope.on(PluginActivated, reject_explicit_wait)
        with pytest.raises(RuntimeError, match="Explicit wait activation failed"):
            await scope.plugin(configured)
        await scope.settle()
        assert registry.plan(call).tool.definition == default
        await remove_listener()
        async with await scope.plugin(configured):
            await scope.settle()
            assert (
                registry.plan(call).tool.definition.description
                == "Wait for the canvas."
            )


async def test_wait_stages_its_pause_under_exclusive_control(monkeypatch):
    pause = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", pause)
    async with mounted(Actions(), WaitTools()) as (services, scope):
        coordination = services.coordination
        tab = services.browser.active_tab

        async def stage(_intent, _staged_tab, step):
            assert coordination.busy
            return await step()

        staged = AsyncMock(side_effect=stage)
        scope[Actions].stage = staged
        result = await scope[ToolRegistry].execute(ToolCall("wait", {"seconds": 2}))
        assert (
            result.text
            == "Wait completed; the next observation shows the current state."
        )
        assert not coordination.busy
    staged.assert_awaited_once()
    assert staged.await_args.args[:2] == (WaitIntent(2), tab)
    pause.assert_awaited_once_with(2)
