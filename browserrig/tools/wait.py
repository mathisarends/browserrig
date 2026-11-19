import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial
from math import inf

from harnessed import Plugin, ToolChain
from harnessed.kernel import Disposer, Key, PluginScope, Scope
from harnessed.tools import ToolRegistry
from pydantic import Field

from browserrig.browser import Browser
from browserrig.core import ActionKind, BrowserToolCall, BrowserToolMetadata

from .execution import Actions
from .intents import WaitIntent

_DEFAULT_MAX_SECONDS = 10
_DEFAULT_DESCRIPTION = "Wait briefly for an expected asynchronous page update."
_SUSPEND_DEFAULT_WAIT = Key[Callable[[], AbstractAsyncContextManager[None]]](
    "browserrig.suspend_default_wait"
)


class WaitTools(
    Plugin,
    slot="browserrig.wait_tools",
    needs=(Actions, Browser, ToolRegistry),
    provides=True,
):
    """Offer a staged wait for an expected page update."""

    def __init__(
        self, max_seconds: float = _DEFAULT_MAX_SECONDS, description: str | None = None
    ) -> None:
        super().__init__()
        if not 0 <= max_seconds < inf:
            raise ValueError("max_seconds must be finite and non-negative")
        self._max_seconds = max_seconds
        self._description = description

    async def setup(self, scope: PluginScope) -> None:
        # Remove the fallback before registering the explicit tool. Navigation observes
        # this provider, so it reinstates the fallback if the explicit plugin is removed.
        suspend_default = scope.get(_SUSPEND_DEFAULT_WAIT)
        if suspend_default is not None:
            await scope.enter(suspend_default())
        _register_wait(scope, self._max_seconds, self._description)


async def mount_default_wait() -> None:
    """Attach navigation's fallback wait to the current plugin activation."""
    scope = Scope.current()
    assert scope is not None
    await scope.plugin(_DefaultWaitTools())


class _DefaultWaitTools(WaitTools, provides=False):
    async def setup(self, scope: PluginScope) -> None:
        if WaitTools in scope:
            return
        dispose = _register_wait(scope, _DEFAULT_MAX_SECONDS, None)
        active = True

        def close() -> None:
            nonlocal active
            active = False

        @asynccontextmanager
        async def suspend() -> AsyncGenerator[None]:
            nonlocal dispose
            await dispose()
            try:
                yield
            finally:
                # Roll back the handoff if navigation still owns this fallback.
                if active:
                    dispose = _register_wait(scope, _DEFAULT_MAX_SECONDS, None)

        scope.effect(close)
        scope.provide(_SUSPEND_DEFAULT_WAIT, suspend)


def _register_wait(
    scope: PluginScope, max_seconds: float, description: str | None
) -> Disposer:
    actions = scope[Actions]
    browser = scope[Browser]
    metadata = BrowserToolMetadata(kind=ActionKind.WAIT)

    async def wait(seconds: float = min(1, max_seconds)) -> object:
        async def perform() -> str:
            await actions.stage(
                WaitIntent(seconds), browser.active_tab, partial(_pause, seconds)
            )
            return "Wait completed; the next observation shows the current state."

        return await scope.dispatch(
            BrowserToolCall(metadata, {"seconds": seconds}), default=perform
        )

    return scope[ToolRegistry].register(
        wait,
        description=_DEFAULT_DESCRIPTION if description is None else description,
        readonly=True,
        owner=scope,
        chain=ToolChain.STOP_AFTER,
        metadata=(metadata,),
        parameter_fields={"seconds": Field(ge=0, le=max_seconds)},
    )


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)
