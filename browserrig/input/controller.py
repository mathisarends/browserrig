import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import replace
from time import monotonic

from browserrig.core.geometry import Bounds, Point
from browserrig.core.kinds import BrowserBar, FileTransferDirection
from browserrig.events import (
    BarTypedEvent,
    FileTransferEvent,
    HighlightElementEvent,
    InputEvent,
    KeyboardVisibilityEvent,
)

from .keyboard import TYPING_INTERVAL_SECONDS, Keyboard
from .mouse import Mouse
from .target import Focus, InputTarget, focused

# Long enough for a viewer to follow a file into its destination, short enough to stay brisk.
_TRANSFER_SECONDS = 0.45
# Bar text is typed at page typing speed, but a long URL speeds up to stay within this.
_BAR_TYPING_SECONDS = 0.8


class Input:
    """The browser's mouse and keyboard, aimed at whichever tab has focus.

    It also correlates every input event with the action that caused it.
    """

    def __init__(self, focus: Focus) -> None:
        self._focus = focus
        self._action_id = ""
        self.mouse = Mouse(focus, emit=self._emit)
        self.keyboard = Keyboard(focus, emit=self._emit)

    @property
    def action_id(self) -> str:
        return self._action_id

    @contextmanager
    def action(self, action_id: str):
        previous, self._action_id = self._action_id, action_id
        try:
            yield
        finally:
            self._action_id = previous

    async def highlight(self, ref: str, bounds: Bounds) -> None:
        """Show which element the next input targets, for live viewers."""
        await self._emit(
            focused(self._focus),
            HighlightElementEvent(
                ref=ref,
                x=bounds.x,
                y=bounds.y,
                width=bounds.width,
                height=bounds.height,
            ),
        )

    async def transfer(
        self,
        direction: FileTransferDirection,
        paths: tuple[str, ...],
        point: Point | None = None,
    ) -> None:
        """Announce files moving into a tab or onto `point`, then hold for the animation."""
        await self._emit(
            focused(self._focus),
            FileTransferEvent(
                direction=direction,
                paths=paths,
                duration=_TRANSFER_SECONDS,
                x=point.x if point is not None else None,
                y=point.y if point is not None else None,
            ),
        )
        await asyncio.sleep(_TRANSFER_SECONDS)

    async def type_in_bar(
        self,
        target: InputTarget,
        browser_bar: BrowserBar,
        text: str,
        *,
        submit: bool = False,
        after_key: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """Show `text` typed key by key into the browser's own `browser_bar` of `target`'s tab.

        Nothing reaches the page. `after_key` runs with the text typed so far, within the
        key's interval, as a browser updates find results while typing.
        """
        interval = min(TYPING_INTERVAL_SECONDS, _BAR_TYPING_SECONDS / max(1, len(text)))
        keys = [(key, text[: index + 1]) for index, key in enumerate(text)]
        if submit:
            keys.append(("Enter", text))
        try:
            await self._emit(target, KeyboardVisibilityEvent(visible=True))
            for key, typed in keys:
                started = monotonic()
                await self._emit(
                    target,
                    BarTypedEvent(
                        browser_bar=browser_bar, key=key, text=typed, duration=interval
                    ),
                )
                if after_key is not None and key != "Enter":
                    await after_key(typed)
                await asyncio.sleep(max(0, interval - (monotonic() - started)))
        finally:
            await self._emit(target, KeyboardVisibilityEvent(visible=False))

    async def announce(self, target: InputTarget, event: InputEvent) -> None:
        """Send a presentation event for `target`'s tab, attributed to the current action."""
        await self._emit(target, event)

    async def _emit(self, target: InputTarget, event: InputEvent) -> None:
        await target.emit(replace(event, action_id=self._action_id))
