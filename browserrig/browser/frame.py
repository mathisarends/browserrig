from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from cdpify import CdpSession
from cdpify.domains.page import FrameTree
from cdpify.domains.runtime import CallArgument
from cdpify.exceptions import CDPCommandError
from pydantic import BaseModel

from browserrig.core import Bounds, BrowserError, FrameTransform
from browserrig.scripts import OWNER_HITS, OwnerHitsArgs, Script, failure

from .worlds import Worlds


@dataclass(frozen=True, slots=True)
class Frame:
    """A CDP page frame: the top-level document or one embedded iframe.

    Its isolated JavaScript world belongs to that frame, not to browser focus.
    `transform` maps frame-local CSS pixels to the tab's viewport; `visible` is the
    part of the frame left unclipped by its ancestors, in viewport pixels.
    """

    id: str
    cdp: CdpSession
    transform: FrameTransform = FrameTransform()
    visible: Bounds | None = None
    parent: Frame | None = None
    owner_id: int | None = None
    document_id: str = ""
    worlds: Worlds = field(default_factory=Worlds, repr=False, compare=False)

    @property
    def local_visible(self) -> Bounds | None:
        """The visible area in this frame's own CSS pixels, for in-page scripts."""
        return (
            self.transform.bounds_to_local(self.visible)
            if self.visible is not None
            else None
        )

    async def frame_tree(self) -> FrameTree:
        result = await self.cdp.page.get_frame_tree()
        return result.frame_tree

    async def upload_files(self, backend_node_id: int, paths: list[str]) -> None:
        try:
            await self.cdp.dom.set_file_input_files(
                files=paths, backend_node_id=backend_node_id
            )
        except CDPCommandError as error:
            raise BrowserError("STALE_ELEMENT") from error

    async def run_on_node[A: BaseModel, R](
        self,
        backend_node_id: int,
        script: Script[A, R],
        args: A | None = None,
        *,
        by_value: bool = True,
        user_gesture: bool = False,
    ) -> R:
        """Run with one of this frame's DOM nodes as `this`, resolved by backend node id."""
        return await self.worlds.run(
            self.cdp,
            self.id,
            self.document_id,
            lambda context: _call_on_node(
                self.cdp,
                backend_node_id,
                script,
                args,
                context,
                by_value=by_value,
                user_gesture=user_gesture,
            ),
        )

    async def run_on_owner[A: BaseModel, R](
        self, script: Script[A, R], args: A | None = None
    ) -> R:
        """Run with this frame's embedding element as `this`, using the same error policy."""
        assert self.parent is not None and self.owner_id is not None
        try:
            return await self.parent.run_on_node(self.owner_id, script, args)
        except BrowserError as error:
            if str(error) == "STALE_ELEMENT":
                raise BrowserError(
                    "Element frame no longer exists; use refs from the next observation"
                ) from error
            raise

    async def check_point(self, x: float, y: float) -> None:
        """A child hit test cannot see blockers in ancestor documents."""
        if not (await self.visible_points(((x, y),)))[0]:
            raise BrowserError("ELEMENT_BLOCKED")

    async def visible_points(
        self, points: tuple[tuple[float, float], ...]
    ) -> tuple[bool, ...]:
        visible = [True] * len(points)
        current = self
        while current.parent is not None:
            visible_area = current.visible
            hits = await current.run_on_owner(
                OWNER_HITS,
                OwnerHitsArgs(
                    points=tuple(
                        current.parent.transform.to_local(x, y) for x, y in points
                    )
                ),
            )
            visible = [
                before
                and hit
                and (visible_area is None or visible_area.contains(*point))
                for before, hit, point in zip(visible, hits, points, strict=True)
            ]
            current = current.parent
        return tuple(visible)

    async def context(self) -> int:
        return await self.worlds.context(self.cdp, self.id, self.document_id)

    async def run[A: BaseModel, R](
        self,
        script: Script[A, R],
        args: A | None = None,
        *,
        objects: Sequence[str] = (),
        by_value: bool = True,
        user_gesture: bool = False,
    ) -> R:
        return await self.worlds.run(
            self.cdp,
            self.id,
            self.document_id,
            lambda context: _call(
                self.cdp,
                script,
                args,
                objects=objects,
                by_value=by_value,
                user_gesture=user_gesture,
                context_id=context,
            ),
            retry=not objects,
        )


async def _call_on_node[A: BaseModel, R](
    cdp: CdpSession,
    backend_node_id: int,
    script: Script[A, R],
    args: A | None,
    context: int,
    *,
    by_value: bool,
    user_gesture: bool,
) -> Any:
    try:
        resolved = await cdp.dom.resolve_node(
            backend_node_id=backend_node_id, execution_context_id=context
        )
    except CDPCommandError as error:
        raise BrowserError("STALE_ELEMENT") from error
    object_id = resolved.object.object_id
    if object_id is None:
        raise BrowserError("STALE_ELEMENT")
    try:
        return await _call(
            cdp,
            script,
            args,
            object_id=object_id,
            by_value=by_value,
            user_gesture=user_gesture,
        )
    finally:
        with suppress(CDPCommandError):
            await cdp.runtime.release_object(object_id=object_id)


async def _call[A: BaseModel, R](
    cdp: CdpSession,
    script: Script[A, R],
    args: A | None,
    *,
    objects: Sequence[str] = (),
    by_value: bool = True,
    user_gesture: bool = False,
    context_id: int | None = None,
    object_id: str | None = None,
) -> Any:
    payload = script.arguments.model_validate({} if args is None else args)
    result = await cdp.runtime.call_function_on(
        function_declaration=script.declaration,
        execution_context_id=context_id,
        object_id=object_id,
        arguments=[
            CallArgument(value=payload.model_dump(mode="json", by_alias=True)),
            *(CallArgument(object_id=node) for node in objects),
        ],
        return_by_value=by_value,
        await_promise=True,
        user_gesture=user_gesture,
    )
    if result.exception_details:
        raise BrowserError(failure(script, result.exception_details))
    return script.parse(result.result.value) if by_value else result.result
