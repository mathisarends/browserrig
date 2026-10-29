import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from cdpify import CdpSession
from cdpify.domains.page import FrameTree
from cdpify.domains.target import TargetInfo
from cdpify.exceptions import CDPCommandError

from .errors import BrowserError
from .geometry import Bounds, Projection
from .tab import Frame, Tab

_MAX_FRAMES = 64
_MAX_DEPTH = 8
_FRAME_TIMEOUT = 2.0

_OWNER_SIZE = """function() {
    for (let el = this; el; el = el.parentElement || el.getRootNode().host) {
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility !== 'visible' ||
            Number(style.opacity) === 0 || el.inert) { return null; }
    }
    const style = getComputedStyle(this);
    return [this.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
            this.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)];
}"""


type _FrameSession = Callable[[str], Awaitable[CdpSession]]


async def discover_frames(
    tab: Tab, targets: tuple[TargetInfo, ...], session_for: _FrameSession
) -> tuple[Frame, ...]:
    """Keep usable siblings when a frame detaches; bound work on frame-heavy pages."""
    root = (await tab.cdp.page.get_frame_tree()).frame_tree
    width, height = await (await tab.main_frame()).evaluate("[innerWidth, innerHeight]")
    viewport = Bounds(x=0, y=0, width=width, height=height)
    result = [Frame(root.frame.id, tab.cdp, Projection(clip=viewport))]
    limitations: list[str] = []
    target_map = {info.target_id: info for info in targets if info.type == "iframe"}
    seen = {root.frame.id}

    async def visit(tree: FrameTree, parent: Frame, session_projection: Projection, depth: int):
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
                    child = await inspect(frame_id, parent, session_projection)
                    if child is None:
                        continue
                    if frame_id in target_map:
                        child_tree = (await child.cdp.page.get_frame_tree()).frame_tree
                result.append(child)
                if child_tree is not None:
                    child_space = child.projection if frame_id in target_map else session_projection
                    await visit(child_tree, child, child_space, depth + 1)
            except (CDPCommandError, BrowserError, TimeoutError, ValueError):
                limitations.append(f"Frame {frame_id} changed or could not be inspected")

    async def inspect(frame_id: str, parent: Frame, space: Projection) -> Frame | None:
        owner = await parent.cdp.dom.get_frame_owner(frame_id=frame_id)
        child = Frame(frame_id, parent.cdp, parent=parent, owner_id=owner.backend_node_id)
        size = await child.owner_call(_OWNER_SIZE)
        if not size or min(size) <= 0:
            return None
        box = await parent.cdp.dom.get_box_model(backend_node_id=owner.backend_node_id)
        projection = space.embed(box.model.content, *size)
        clip = projection.box(Bounds(x=0, y=0, width=size[0], height=size[1]))
        clip = clip.intersect(parent.projection.clip or viewport)
        if clip.width <= 0 or clip.height <= 0:
            return None
        # BoxModel quads are relative to the CDP session's root, not the parent frame.
        cdp = await session_for(frame_id) if frame_id in target_map else parent.cdp
        return replace(child, cdp=cdp, projection=replace(projection, clip=clip))

    try:
        async with asyncio.timeout(10):
            await visit(root, result[0], Projection(), 0)
    except TimeoutError:
        limitations.append("Frame discovery timed out; some frames could not be inspected")
    tab.frame_limitations = tuple(dict.fromkeys(limitations))
    return tuple(result)
