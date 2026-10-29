import asyncio
from contextlib import suppress

from cdpify.domains.domsnapshot import CaptureSnapshotResult
from cdpify.domains.runtime import CallArgument
from cdpify.exceptions import CDPCommandError

from browserrig.browser.tab import Frame

_SEED_SCRIPT = """function(clickable, ...nodes) {
    globalThis.__browserrigDOM = {
        roots: Array.from(new Set(nodes.map(node => node.getRootNode())
            .filter(root => root.mode === 'closed'))),
        clickable: new WeakSet(nodes.filter((node, index) => clickable[index])),
    };
}"""


async def seed_dom(frame: Frame, snapshot: CaptureSnapshotResult) -> bool:
    """Supplement the composed DOM walk with closed roots and native click-listener metadata."""
    document = next(
        (doc for doc in snapshot.documents if snapshot.strings[doc.frame_id] == frame.id), None
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
            if snapshot.strings[value] == "closed" and (nodes.node_type or [])[index] == 1
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
                    backend_node_id=ids[index], execution_context_id=context, object_group=group
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
            await frame.cdp.runtime.call_function_on(
                function_declaration=_SEED_SCRIPT,
                execution_context_id=context,
                arguments=[
                    CallArgument(value=[index in clickable for index, _ in resolved]),
                    *(CallArgument(object_id=object_id) for _, object_id in resolved),
                ],
            )
        return len(indexes) <= 256 and all(objects)
    finally:
        with suppress(CDPCommandError, TimeoutError):
            await frame.cdp.runtime.release_object_group(object_group=group)
