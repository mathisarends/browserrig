from typing import Any

from harnessed import Context, Inject, Plugin, hook
from harnessed.events import TurnStartedEvent
from harnessed.hooks import Next

from browserrig.browser import Browser
from browserrig.events import INPUT_EVENTS
from browserrig.tools import (
    FindIntent,
    NavigateIntent,
    OpenFileIntent,
    Perform,
    TargetLocated,
    UploadIntent,
    WaitIntent,
)

from . import scenes
from .events import SCENE_EVENTS, HighlightElementEvent
from .stage import Stage


class Choreography(Plugin, slot="browserrig.choreography", needs=(Browser,)):
    """Stage the browser for people watching: visible input and browser UI.

    Tools and input devices only describe what they do. This plugin streams input as
    live events, shows browser UI such as the address and find bars and highlights the
    elements tools act on. How fast input runs is up to `Pacing`. Without this plugin
    no input events are emitted.
    """

    events = INPUT_EVENTS + SCENE_EVENTS
    _browser: Inject[Browser]

    async def setup(self, ctx: Context) -> None:
        inputs = self._browser.input
        ctx.effect(inputs.present(Stage(lambda: inputs.action_id)))

        async def publish_cursor(_event: TurnStartedEvent) -> None:
            # Live subscribers often attach late, so seed their cursor at turn start.
            await inputs.mouse.publish_cursor()

        ctx.on(TurnStartedEvent, publish_cursor)

    @hook(Perform)
    async def _stage(self, event: Perform, next_: Next[Any]) -> Any:
        scene = scenes.Scene(event.tab, event.action_id)
        match event.intent:
            case FindIntent() as intent:
                return await scenes.find(scene, intent, next_)
            case NavigateIntent() as intent:
                return await scenes.navigate(scene, intent, next_)
            case WaitIntent() as intent:
                return await scenes.wait(scene, intent, next_)
            case OpenFileIntent() as intent:
                return await scenes.open_file(scene, intent, next_)
            case UploadIntent() as intent:
                return await scenes.upload(scene, intent, next_)
        return await next_()

    @hook(TargetLocated)
    async def _highlight(self, event: TargetLocated) -> None:
        bounds = event.bounds
        await event.tab.emit(
            HighlightElementEvent(
                ref=event.ref,
                x=bounds.x,
                y=bounds.y,
                width=bounds.width,
                height=bounds.height,
                action_id=event.action_id,
            )
        )
