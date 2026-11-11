from dataclasses import dataclass

from harnessed import Plugin, PluginState, hook
from harnessed.hooks import Next
from harnessed.kernel import PluginScope, needs

from browserrig.core import ActionContext, ChangeTab
from browserrig.events import TabActivatedEvent, TabClosedEvent

from .controller import Input
from .target import InputTargets


@dataclass
class _Devices:
    input: Input | None = None
    switching: int = 0


class InputRuntime(Plugin, slot="browserrig.input"):
    """Own a session's devices and bind them to the backend's input targets."""

    _targets = needs(InputTargets)
    _actions = needs(ActionContext)
    _state = PluginState(_Devices)

    async def setup(self, scope: PluginScope) -> None:
        devices = self._state.input = Input(
            self._targets.focused, action_id=lambda: self._actions.action_id
        )
        scope.provide(Input, devices)
        scope.on(TabActivatedEvent, self._activated)
        scope.on(TabClosedEvent, self._closed)
        # Chrome may already have focused its initial tab before this plugin mounts.
        if self._targets.focused() is not None:
            await devices.mouse.resume()

    @hook(ChangeTab)
    async def _change(self, event: ChangeTab, next_: Next[None]) -> None:
        if self._state.input is None:
            # The backend can open its initial tab before devices are mounted.
            await next_()
            return
        self._state.switching += 1
        try:
            await self._devices.mouse.switch_tab(event.gesture, event.target_id, next_)
        finally:
            self._state.switching -= 1

    async def _activated(self, _event: TabActivatedEvent) -> None:
        if self._state.switching:
            return
        target = self._targets.focused()
        if target is None:
            return
        mouse = self._devices.mouse
        if mouse.position_in(target.id) is None:
            await mouse.resume()
        else:
            # Re-selecting the active tab republishes state without firing hover again.
            await mouse.publish_cursor()

    async def _closed(self, event: TabClosedEvent) -> None:
        self._devices.mouse.forget(event.target_id)

    @property
    def _devices(self) -> Input:
        devices = self._state.input
        assert devices is not None
        return devices
