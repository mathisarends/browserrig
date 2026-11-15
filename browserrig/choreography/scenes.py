"""How each staged tool step looks to viewers, around the step itself."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any
from uuid import uuid4

from cdpify import CDPCommandError

from browserrig.browser import Tab
from browserrig.core import (
    BrowserBar,
    BrowserControl,
    BrowserError,
    FileTransferDirection,
    Point,
)
from browserrig.events import (
    InputEvent,
    KeyboardVisibilityEvent,
    KeyPressedEvent,
    TabEvent,
)
from browserrig.input import TYPING_INTERVAL_SECONDS
from browserrig.observation import PageSearch, close_find, find_text
from browserrig.scripts import TargetScrollResult
from browserrig.tools import (
    ControlIntent,
    DomScrollIntent,
    NavigateIntent,
    OpenFileIntent,
    SearchIntent,
    UploadIntent,
    WaitIntent,
)

from .events import (
    AddressBarFocusedEvent,
    BackPressedEvent,
    BarTypedEvent,
    CursorEnteredEvent,
    ElementScrolledEvent,
    FileTransferEvent,
    FindBarEvent,
    FindResultsEvent,
    ForwardPressedEvent,
    PageScrolledEvent,
    ReloadPressedEvent,
    ToolbarPressedEvent,
    WaitingEvent,
)
from .stage import ENTER_SECONDS, PRESS_SECONDS

type Step = Callable[[], Awaitable[Any]]

# The event each history or reload button shows when the pointer presses it.
_PRESSED: dict[BrowserControl, type[ToolbarPressedEvent]] = {
    BrowserControl.BACK: BackPressedEvent,
    BrowserControl.FORWARD: ForwardPressedEvent,
    BrowserControl.RELOAD: ReloadPressedEvent,
}
# Bar text is typed at a person's typing speed, but a long URL speeds up to stay within this.
_BAR_TYPING_SECONDS = 0.8
# Long enough for a viewer to follow a file into its destination, short enough to stay brisk.
_TRANSFER_SECONDS = 0.45
# How long viewers see the final results before the find bar closes.
_FIND_HOLD_SECONDS = 0.6
# Alternatives appear in the find bar joined by this, typed like one text.
_OR = " | "


@dataclass(frozen=True, slots=True)
class Scene:
    """Where a step is staged: its tab, the action it belongs to and the pointer.

    `pointer` is where the pointer rests in the tab, or None before it has been there.
    """

    tab: Tab
    action_id: str
    pointer: Point | None = None

    async def show(self, event: InputEvent | TabEvent) -> None:
        await self.tab.emit(replace(event, action_id=self.action_id))


async def dom_scroll(
    scene: Scene, intent: DomScrollIntent, step: Step
) -> TargetScrollResult:
    result: TargetScrollResult = await step()
    if result.before != result.after:
        dx = result.after.x - result.before.x
        dy = result.after.y - result.before.y
        receipt = (
            ElementScrolledEvent(ref=intent.ref, delta_x=dx, delta_y=dy)
            if intent.ref
            else PageScrolledEvent(delta_x=dx, delta_y=dy)
        )
        await scene.show(receipt)
    return result


async def search(scene: Scene, intent: SearchIntent, step: Step) -> PageSearch:
    """Ctrl+F with the queries typed and their text marked live, then the records found.

    Marks and counts are drawn over the page; the page itself never scrolls or changes.
    """
    shown = _OR.join(intent.queries)
    session = uuid4().hex

    async def results(text: str, queries: tuple[str, ...], label: str = "") -> None:
        try:
            found = await find_text(scene.tab, queries, session=session, ticks=True)
        except (CDPCommandError, BrowserError, TimeoutError):
            # Presentation must never fail the search itself.
            return
        await scene.show(
            FindResultsEvent(
                query=text,
                total=found.total,
                label=label or _count(found.total, "match", "matches"),
                marks=found.marks,
                ticks=found.ticks,
            )
        )

    async def preview(typed: str) -> None:
        # Like a browser's find bar: results follow each key, without scrolling.
        if typing := _typed(intent.queries, len(typed)):
            await results(typed, typing)

    await scene.show(KeyPressedEvent(key="f", modifiers=("Control",)))
    await scene.show(FindBarEvent(visible=True))
    try:
        await _type_in_bar(scene, BrowserBar.FIND, shown, after_key=preview)
        found: PageSearch = await step()
        await results(shown, intent.queries, _count(found.total, "record", "records"))
        await asyncio.sleep(_FIND_HOLD_SECONDS)
        return found
    finally:
        await scene.show(KeyPressedEvent(key="Escape"))
        await scene.show(FindBarEvent(visible=False))
        await close_find(scene.tab)


async def navigate(scene: Scene, intent: NavigateIntent, step: Step) -> Any:
    """The address bar pressed, the address typed and submitted, then the page loading."""
    async with _pressed(scene, AddressBarFocusedEvent):
        await _type_in_bar(scene, BrowserBar.ADDRESS, intent.typed, submit=True)
        return await step()


async def press(scene: Scene, intent: ControlIntent, step: Step) -> Any:
    """The toolbar control pressed before the step, as a person goes back or reloads."""
    async with _pressed(scene, _PRESSED[intent.control]):
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


@asynccontextmanager
async def _pressed(
    scene: Scene, pressed: type[ToolbarPressedEvent]
) -> AsyncGenerator[None]:
    """The pointer travels to a toolbar control and presses it, then returns.

    The return follows whatever the control does; if that fails or is cancelled, the
    pointer is back at once. Without a place in the page it has nowhere to return to.
    """
    start = scene.pointer
    position = (start.x, start.y) if start is not None else None
    await scene.show(pressed(from_position=position, duration=PRESS_SECONDS))
    duration = ENTER_SECONDS
    try:
        await asyncio.sleep(PRESS_SECONDS)
        yield
    except BaseException:
        duration = 0
        raise
    finally:
        if position is not None:
            await scene.show(
                CursorEnteredEvent(to_position=position, duration=duration)
            )
            if duration:
                await asyncio.sleep(duration)


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


def _count(total: int, one: str, many: str) -> str:
    return f"{total} {one if total == 1 else many}"


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
