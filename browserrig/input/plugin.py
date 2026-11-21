from dataclasses import dataclass

from harnessed import Plugin
from harnessed.hooks import Next
from harnessed.kernel import PluginScope, PluginState, hook, needs

from browserrig.core import ActionContext, ChangeTab
from browserrig.events import TabActivatedEvent, TabClosedEvent

from .controller import Input, InputSettings
from .keyboard import Keyboard
from .mouse import Mouse
from .target import InputTargets
from .touch import Touch


@dataclass
class _MouseState:
    mouse: Mouse | None = None
    switching: int = 0


class _MouseLifecycle(Plugin):
    """Provide a mouse and synchronize its cursor when tabs change."""

    _targets = needs(InputTargets)
    _state = PluginState(_MouseState)

    async def _install(self, scope: PluginScope, mouse: Mouse) -> None:
        self._state.mouse = mouse
        scope.provide(Mouse, mouse)
        scope.on(TabActivatedEvent, self._activated)
        scope.on(TabClosedEvent, self._closed)
        # Chrome may already have focused its initial tab before this plugin mounts.
        if self._targets.focused() is not None:
            await mouse.resume()

    @hook(ChangeTab)
    async def _change(self, event: ChangeTab, next_: Next[None]) -> None:
        if self._state.mouse is None:
            # The backend can open its initial tab before devices are mounted.
            await next_()
            return
        self._state.switching += 1
        try:
            await self._mouse.switch_tab(event.gesture, event.target_id, next_)
        finally:
            self._state.switching -= 1

    async def _activated(self, _event: TabActivatedEvent) -> None:
        if self._state.switching:
            return
        target = self._targets.focused()
        if target is None:
            return
        mouse = self._mouse
        if mouse.position_in(target.id) is None:
            await mouse.resume()
        else:
            # Re-selecting the active tab republishes state without firing hover again.
            await mouse.publish_cursor()

    async def _closed(self, event: TabClosedEvent) -> None:
        self._mouse.forget(event.target_id)

    @property
    def _mouse(self) -> Mouse:
        mouse = self._state.mouse
        assert mouse is not None
        return mouse


class DeviceRuntime(Plugin, slot="browserrig.input"):
    """Provide shared pacing and presentation for an explicit device composition."""

    _actions = needs(ActionContext)

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(
            InputSettings, InputSettings(action_id=lambda: self._actions.action_id)
        )


class KeyboardInput(Plugin):
    """Provide keyboard input to the focused tab."""

    _targets = needs(InputTargets)
    _settings = needs(InputSettings)

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(Keyboard, self._settings.create_keyboard(self._targets.focused))


class MouseInput(_MouseLifecycle):
    """Provide mouse input and synchronize the cursor on tab activation."""

    _settings = needs(InputSettings)

    async def setup(self, scope: PluginScope) -> None:
        await self._install(scope, self._settings.create_mouse(self._targets.focused))


class TouchInput(Plugin):
    """Provide single-finger touch gestures to the focused tab."""

    _targets = needs(InputTargets)

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(Touch, Touch(self._targets.focused))


class InputRuntime(_MouseLifecycle, slot="browserrig.input"):
    """Provide the standard desktop mouse, keyboard and direct Input facade."""

    _actions = needs(ActionContext)

    async def setup(self, scope: PluginScope) -> None:
        devices = Input(
            self._targets.focused, action_id=lambda: self._actions.action_id
        )
        scope.provide(Input, devices)
        scope.provide(InputSettings, devices)
        scope.provide(Keyboard, devices.keyboard)
        await self._install(scope, devices.mouse)
