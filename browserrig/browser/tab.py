from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cdpify import CdpSession
from cdpify.domains.runtime import CallArgument

from .errors import BrowserError
from .geometry import Bounds, Projection


@dataclass(frozen=True, slots=True)
class Frame:
    """A CDP page frame: the top-level document or one embedded iframe.

    Its isolated JavaScript world belongs to that frame, not to browser focus.
    Its projection maps frame-local CSS pixels to the containing tab's viewport.
    """

    id: str
    cdp: CdpSession
    projection: Projection = Projection()
    parent: Frame | None = None
    owner_id: int | None = None

    @property
    def x(self) -> float:
        return self.projection.x

    @property
    def y(self) -> float:
        return self.projection.y

    @property
    def local_clip(self) -> Bounds | None:
        clip = self.projection.clip
        return self.projection.local_box(clip) if clip is not None else None

    async def owner_call(self, function: str, *arguments: object) -> Any:
        """Inspect the embedding element in its parent's isolated world."""
        assert self.parent is not None and self.owner_id is not None
        cdp = self.parent.cdp
        resolved = await cdp.dom.resolve_node(
            backend_node_id=self.owner_id, execution_context_id=await self.parent.context()
        )
        object_id = resolved.object.object_id
        if object_id is None:
            raise BrowserError("Element frame no longer exists; observe again")
        try:
            result = await cdp.runtime.call_function_on(
                object_id=object_id,
                function_declaration=function,
                arguments=[CallArgument(value=value) for value in arguments],
                return_by_value=True,
            )
            if result.exception_details:
                raise BrowserError("Frame owner could not be inspected")
            return result.result.value
        finally:
            await cdp.runtime.release_object(object_id=object_id)

    async def check_point(self, x: float, y: float) -> None:
        """A child hit test cannot see blockers in ancestor documents."""
        if not (await self.visible_points(((x, y),)))[0]:
            raise BrowserError("ELEMENT_BLOCKED")

    async def visible_points(self, points: tuple[tuple[float, float], ...]) -> tuple[bool, ...]:
        visible = [True] * len(points)
        current = self
        while current.parent is not None:
            clip = current.projection.clip
            hits = await current.owner_call(
                """function(points) {
                    return points.map(([x, y]) => {
                        let root = this.getRootNode(), target = this;
                        while (root) {
                            const hit = root.elementFromPoint(x, y);
                            if (hit !== target) { return false; }
                            target = root.host;
                            root = target?.getRootNode();
                        }
                        return true;
                    });
                }""",
                [current.parent.projection.inverse(x, y) for x, y in points],
            )
            visible = [
                before and hit and (clip is None or clip.contains(*point))
                for before, hit, point in zip(visible, hits, points, strict=True)
            ]
            current = current.parent
        return tuple(visible)

    async def context(self) -> int:
        result = await self.cdp.page.create_isolated_world(
            frame_id=self.id, world_name="browserrig"
        )
        return result.execution_context_id

    async def evaluate(self, expression: str) -> Any:
        result = await self.cdp.runtime.evaluate(
            expression=expression,
            context_id=await self.context(),
            return_by_value=True,
            await_promise=True,
        )
        if result.exception_details:
            raise BrowserError("Page script failed in the isolated browserrig world")
        return result.result.value

    async def call(self, function: str, *arguments: object, by_value: bool = True) -> Any:
        result = await self.cdp.runtime.call_function_on(
            function_declaration=function,
            execution_context_id=await self.context(),
            arguments=[CallArgument(value=value) for value in arguments],
            return_by_value=by_value,
            await_promise=True,
            user_gesture=True,
        )
        if result.exception_details:
            detail = result.exception_details.exception
            message = detail.description if detail else result.exception_details.text
            # Scripts use fixed error codes; never expose arbitrary page exceptions.
            for code in (
                "STALE_ELEMENT",
                "ELEMENT_BLOCKED",
                "ELEMENT_DISABLED",
                "NOT_EDITABLE",
                "OPTION_NOT_FOUND",
                "NOT_A_SELECT",
                "INVALID_VALUE",
            ):
                if code in (message or ""):
                    raise BrowserError(code)
            raise BrowserError("Element operation failed in the page")
        return result.result.value if by_value else result.result


class Tab:
    """A stable target/session pair. It never follows global browser focus."""

    def __init__(self, target_id: str, cdp: CdpSession) -> None:
        self.id = target_id
        self.cdp = cdp
        self.document_id = ""
        self.url = "about:blank"
        self.title = ""
        self.dialog: tuple[str, str] | None = None
        self.closed = False
        self.changed = asyncio.Event()
        self.frame_limitations: tuple[str, ...] = ()

    async def main_frame(self) -> Frame:
        tree = await self.cdp.page.get_frame_tree()
        self.document_id = tree.frame_tree.frame.loader_id
        self.url = tree.frame_tree.frame.url
        return Frame(tree.frame_tree.frame.id, self.cdp)

    async def evaluate(self, expression: str) -> Any:
        return await (await self.main_frame()).evaluate(expression)

    async def navigate(self, url: str) -> None:
        result = await self.cdp.page.navigate(url=validated_url(url))
        if result.error_text:
            raise BrowserError(f"Navigation failed: {result.error_text}")

    async def press_key(self, key: str) -> None:
        """Dispatch input to this tab's page session, never to browser chrome or the OS."""
        modifiers = 0
        parts = key.split("+")
        for part in parts[:-1]:
            flag = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}.get(part)
            if flag is None:
                raise BrowserError("Unknown key modifier; use Alt, Control, Meta or Shift")
            modifiers |= flag
        actual = parts[-1]
        codes = {
            "Enter": 13,
            "Tab": 9,
            "Escape": 27,
            "Backspace": 8,
            "Delete": 46,
            "ArrowLeft": 37,
            "ArrowUp": 38,
            "ArrowRight": 39,
            "ArrowDown": 40,
            "Home": 36,
            "End": 35,
            "PageUp": 33,
            "PageDown": 34,
        }
        if len(actual) != 1 and actual not in codes:
            raise BrowserError("Unsupported key")
        arguments: dict[str, Any] = {"key": actual, "modifiers": modifiers}
        if actual in codes:
            arguments["windows_virtual_key_code"] = codes[actual]
        if actual == "Enter":
            arguments["text"] = "\r"
        if len(actual) == 1 and actual.isascii() and actual.isalnum():
            arguments["windows_virtual_key_code"] = ord(actual.upper())
        try:
            await self.cdp.input.dispatch_key_event(type="keyDown", **arguments)
            if len(actual) == 1 and modifiers == 0:
                await self.cdp.input.insert_text(text=actual)
        finally:
            arguments.pop("text", None)
            await self.cdp.input.dispatch_key_event(type="keyUp", **arguments)


def validated_url(url: str) -> str:
    parsed = urlsplit(url)
    if url == "about:blank" or parsed.scheme in {"http", "https"} and parsed.hostname:
        return url
    raise BrowserError("Navigation requires an HTTP(S) URL or about:blank")


def script_call(script: str, arguments: dict[str, object]) -> str:
    return f"({script})({json.dumps(arguments, ensure_ascii=True)})"
