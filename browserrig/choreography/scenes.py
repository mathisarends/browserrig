"""How each staged tool step looks to viewers, around the step itself."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any

from browserrig.browser import Tab
from browserrig.core import BrowserBar, FileTransferDirection, Point
from browserrig.events import InputEvent, KeyboardVisibilityEvent, KeyPressedEvent
from browserrig.observation import PageMatches, find_text
from browserrig.tools import (
    FindIntent,
    NavigateIntent,
    OpenFileIntent,
    UploadIntent,
    WaitIntent,
)

from .events import (
    BarTypedEvent,
    FileTransferEvent,
    FindBarEvent,
    FindResultsEvent,
    WaitingEvent,
)
from .pacing import TYPING_INTERVAL_SECONDS

type Step = Callable[[], Awaitable[Any]]

# Bar text is typed at page typing speed, but a long URL speeds up to stay within this.
_BAR_TYPING_SECONDS = 0.8
# Long enough for a viewer to follow a file into its destination, short enough to stay brisk.
_TRANSFER_SECONDS = 0.45
# How long viewers see the final results before the find bar closes.
_FIND_HOLD_SECONDS = 0.6
# Alternatives appear in the find bar joined by this, typed like one text.
_OR = " | "


@dataclass(frozen=True, slots=True)
class Scene:
    """Where a step is staged: its tab and the action it belongs to."""

    tab: Tab
    action_id: str

    async def show(self, event: InputEvent) -> None:
        await self.tab.emit(replace(event, action_id=self.action_id))


async def find(scene: Scene, intent: FindIntent, step: Step) -> PageMatches:
    """Ctrl+F, the queries typed into the find bar with live results, then Escape."""
    shown = _OR.join(intent.queries)

    async def preview(typed: str) -> None:
        # Like a browser's find bar: results follow each key, without scrolling.
        if typing := _typed(intent.queries, len(typed)):
            found = await find_text(scene.tab, typing, session=intent.session)
            await scene.show(_results(typed, found, current=1))

    await scene.show(KeyPressedEvent(key="f", modifiers=("Control",)))
    await scene.show(FindBarEvent(visible=True))
    try:
        await _type_in_bar(scene, BrowserBar.FIND, shown, after_key=preview)
        found: PageMatches = await step()
        await scene.show(_results(shown, found, current=intent.match))
        await asyncio.sleep(_FIND_HOLD_SECONDS)
        return found
    finally:
        await scene.show(KeyPressedEvent(key="Escape"))
        await scene.show(FindBarEvent(visible=False))


async def navigate(scene: Scene, intent: NavigateIntent, step: Step) -> Any:
    """The address typed into the bar and submitted before the page starts loading."""
    await _type_in_bar(scene, BrowserBar.ADDRESS, intent.typed, submit=True)
    return await step()


async def wait(scene: Scene, intent: WaitIntent, step: Step) -> Any:
    await scene.show(WaitingEvent(duration=intent.seconds))
    return await step()


async def open_file(scene: Scene, intent: OpenFileIntent, step: Step) -> Any:
    """The file leaves the current tab first, so viewers can follow it into the new one."""
    await _transfer(scene, FileTransferDirection.OPEN, (intent.path,))
    return await step()


async def upload(scene: Scene, intent: UploadIntent, step: Step) -> Any:
    await _transfer(scene, FileTransferDirection.UPLOAD, intent.paths, intent.point)
    return await step()


async def _type_in_bar(
    scene: Scene,
    browser_bar: BrowserBar,
    text: str,
    *,
    submit: bool = False,
    after_key: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    """Show `text` typed key by key into the browser's own `browser_bar`.

    Nothing reaches the page. `after_key` runs with the text typed so far, within the
    key's interval, as a browser updates find results while typing.
    """
    interval = min(TYPING_INTERVAL_SECONDS, _BAR_TYPING_SECONDS / max(1, len(text)))
    keys = [(key, text[: index + 1]) for index, key in enumerate(text)]
    if submit:
        keys.append(("Enter", text))
    try:
        await scene.show(KeyboardVisibilityEvent(visible=True))
        for key, typed in keys:
            started = monotonic()
            await scene.show(
                BarTypedEvent(
                    browser_bar=browser_bar, key=key, text=typed, duration=interval
                )
            )
            if after_key is not None and key != "Enter":
                await after_key(typed)
            await asyncio.sleep(max(0, interval - (monotonic() - started)))
    finally:
        await scene.show(KeyboardVisibilityEvent(visible=False))


async def _transfer(
    scene: Scene,
    direction: FileTransferDirection,
    paths: tuple[str, ...],
    point: Point | None = None,
) -> None:
    await scene.show(
        FileTransferEvent(
            direction=direction,
            paths=paths,
            duration=_TRANSFER_SECONDS,
            x=point.x if point is not None else None,
            y=point.y if point is not None else None,
        )
    )
    await asyncio.sleep(_TRANSFER_SECONDS)


def _results(query: str, found: PageMatches, *, current: int) -> FindResultsEvent:
    return FindResultsEvent(
        query=query,
        total=found.total,
        active=current if current <= found.total else 0,
        marks=found.marks,
    )


def _typed(queries: tuple[str, ...], length: int) -> tuple[str, ...]:
    """The alternatives typed so far once the find bar holds `length` characters."""
    typed = []
    position = 0
    for query in queries:
        if position >= length:
            break
        typed.append(query[: length - position].strip())
        position += len(query) + len(_OR)
    return tuple(query for query in typed if query)
