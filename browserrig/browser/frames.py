import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from cdpify import CdpSession
from cdpify.domains.page import FrameTree
from cdpify.domains.target import TargetInfo
from cdpify.exceptions import CDPCommandError

from browserrig.core import Bounds, BrowserError, FrameTransform
from browserrig.scripts import OWNER_SIZE, VIEWPORT

from .frame import Frame
from .tab import Tab

_MAX_FRAMES = 64
_MAX_DEPTH = 8
_FRAME_TIMEOUT = 2.0

type _FrameSession = Callable[[str], Awaitable[CdpSession]]


async def discover_frames(
    tab: Tab, targets: tuple[TargetInfo, ...], session_for: _FrameSession
) -> tuple[tuple[Frame, ...], tuple[str, ...]]:
    """Return the tab's frames and why any were skipped.

    Keep usable siblings when a frame detaches; bound work on frame-heavy pages.
    """
    root = await tab.frame_tree()
    width, height = await (await tab.main_frame()).run(VIEWPORT)
    viewport = Bounds(x=0, y=0, width=width, height=height)
    result = [
        Frame(
            root.frame.id,
            tab.cdp,
            visible=viewport,
            document_id=root.frame.loader_id,
            worlds=tab.worlds,
        )
    ]
    limitations: list[str] = []
    target_map = {info.target_id: info for info in targets if info.type == "iframe"}
    seen = {root.frame.id}

    async def visit(
        tree: FrameTree, parent: Frame, session_space: FrameTransform, depth: int
    ):
        children: dict[str, FrameTree | None] = {
            child.frame.id: child for child in tree.child_frames or ()
        }
        # Some OOPIFs appear only in target discovery, not the embedding session's tree.
        children.update(
            (info.target_id, children.get(info.target_id))
            for info in targets
            if info.type == "iframe" and info.parent_frame_id == parent.id
        )
        for frame_id, child_tree in children.items():
            if frame_id in seen:
                continue
            seen.add(frame_id)
            if len(result) >= _MAX_FRAMES or depth >= _MAX_DEPTH:
                limitations.append("Frame count or nesting limit reached")
                return
            try:
                async with asyncio.timeout(_FRAME_TIMEOUT):
                    child = await inspect(frame_id, parent, session_space)
                    if child is None:
                        continue
                    if frame_id in target_map:
                        child_tree = await child.frame_tree()
                    if child_tree is not None:
                        child = replace(child, document_id=child_tree.frame.loader_id)
                result.append(child)
                if child_tree is not None:
                    child_space = (
                        child.transform if frame_id in target_map else session_space
                    )
                    await visit(child_tree, child, child_space, depth + 1)
            except (CDPCommandError, BrowserError, TimeoutError, ValueError):
                limitations.append(
                    f"Frame {frame_id} changed or could not be inspected"
                )

    async def inspect(
        frame_id: str, parent: Frame, space: FrameTransform
    ) -> Frame | None:
        owner = await parent.cdp.dom.get_frame_owner(frame_id=frame_id)
        child = Frame(
            frame_id,
            parent.cdp,
            parent=parent,
            owner_id=owner.backend_node_id,
            worlds=tab.worlds,
        )
        size = await child.run_on_owner(OWNER_SIZE)
        if not size or min(size) <= 0:
            return None
        box = await parent.cdp.dom.get_box_model(backend_node_id=owner.backend_node_id)
        transform = space.child(box.model.content, *size)
        visible = transform.bounds_to_viewport(
            Bounds(x=0, y=0, width=size[0], height=size[1])
        )
        visible = visible.intersect(parent.visible or viewport)
        # BoxModel quads are relative to the CDP session's root, not the parent frame.
        cdp = await session_for(frame_id) if frame_id in target_map else parent.cdp
        return replace(child, cdp=cdp, transform=transform, visible=visible)

    try:
        async with asyncio.timeout(10):
            await visit(root, result[0], FrameTransform(), 0)
    except TimeoutError:
        limitations.append(
            "Frame discovery timed out; some frames could not be inspected"
        )
    return tuple(result), tuple(dict.fromkeys(limitations))
