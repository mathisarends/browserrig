import asyncio
from contextlib import suppress

from cdpify.domains.domsnapshot import CaptureSnapshotResult
from cdpify.exceptions import CDPCommandError

from browserrig.browser import Frame
from browserrig.scripts import RESET, SEED, SeedArgs


async def seed_frame(
    frame: Frame,
    metadata: dict[str, CaptureSnapshotResult | None],
    limitations: list[str],
) -> None:
    await frame.run(RESET)
    try:
        session_id = frame.cdp.session_id
        if session_id not in metadata:
            metadata[session_id] = None
            async with asyncio.timeout(2):
                metadata[session_id] = await frame.cdp.dom_snapshot.capture_snapshot(
                    computed_styles=[]
                )
        snapshot = metadata[session_id]
        if snapshot is None or not await _seed_dom(frame, snapshot):
            limitations.append(
                f"Supplementary DOM metadata incomplete for frame {frame.id}"
            )
    except (CDPCommandError, TimeoutError):
        limitations.append(
            f"Supplementary DOM metadata unavailable for frame {frame.id}"
        )


async def _seed_dom(frame: Frame, snapshot: CaptureSnapshotResult) -> bool:
    """Supplement the composed DOM walk with closed roots and native click-listener metadata."""
    document = next(
        (
            doc
            for doc in snapshot.documents
            if snapshot.strings[doc.frame_id] == frame.id
        ),
        None,
    )
    if document is None:
        return False
    nodes = document.nodes
    ids = nodes.backend_node_id or []
    roots = nodes.shadow_root_type
    closed = (
        [
            index
            for index, value in zip(roots.index, roots.value, strict=True)
            if snapshot.strings[value] == "closed"
            and (nodes.node_type or [])[index] == 1
        ]
        if roots
        else []
    )
    clickable = set(nodes.is_clickable.index if nodes.is_clickable else [])
    indexes = list(dict.fromkeys([*closed, *sorted(clickable)]))
    context = await frame.context()
    group = f"browserrig-dom:{frame.id}"
    semaphore = asyncio.Semaphore(8)

    async def resolve(index: int) -> str | None:
        async with semaphore:
            try:
                node = await frame.cdp.dom.resolve_node(
                    backend_node_id=ids[index],
                    execution_context_id=context,
                    object_group=group,
                )
                return node.object.object_id
            except CDPCommandError:
                return None

    try:
        async with asyncio.timeout(2):
            objects = await asyncio.gather(*(resolve(index) for index in indexes[:256]))
            resolved = [
                (index, object_id)
                for index, object_id in zip(indexes[:256], objects, strict=True)
                if object_id is not None
            ]
            await frame.run(
                SEED,
                SeedArgs(clickable=tuple(index in clickable for index, _ in resolved)),
                objects=tuple(object_id for _, object_id in resolved),
            )
        # Click listeners only refine hints; a missed closed root hides content.
        missed = set(closed) - {index for index, _ in resolved}
        return not missed
    finally:
        with suppress(CDPCommandError, TimeoutError):
            await frame.cdp.runtime.release_object_group(object_group=group)
