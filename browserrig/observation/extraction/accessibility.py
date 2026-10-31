"""Accessible names from Chrome's accessibility tree for the controls an observation lists.

The DOM snapshot only approximates accname. Chrome's own computation also covers
visually hidden text, SVG titles, placeholders and CSS-generated content. Querying just
the listed controls keeps the cost to a few milliseconds even on very large pages.
"""

import asyncio
import re
from collections.abc import Iterable

from cdpify import CdpSession

from ..models import Element
from .document import clean

_TIMEOUT = 2
_NON_WORD = re.compile(r"\W+")


async def chrome_names(
    sessions: dict[str, CdpSession], elements: Iterable[Element]
) -> dict[str, str]:
    """Chrome's accessible name per element ref; elements Chrome leaves unnamed are omitted."""
    queried = [element for element in elements if element.frame_id in sessions]
    try:
        async with asyncio.timeout(_TIMEOUT):
            names = await asyncio.gather(
                *(
                    _name(sessions[element.frame_id], element.backend_id)
                    for element in queried
                ),
                return_exceptions=True,
            )
    except TimeoutError:
        return {}
    return {
        element.ref: name
        for element, name in zip(queried, names, strict=True)
        if isinstance(name, str) and name
    }


def preferred(own: str, chrome: str) -> str:
    """Chrome's name, unless it only differs from ours in case, spacing or icon glyphs."""
    if (
        not chrome
        or _NON_WORD.sub("", chrome).casefold() == _NON_WORD.sub("", own).casefold()
    ):
        return own
    return chrome


async def _name(cdp: CdpSession, backend_id: int) -> str:
    result = await cdp.accessibility.get_partial_ax_tree(
        backend_node_id=backend_id, fetch_relatives=False
    )
    for node in result.nodes:
        if node.backend_dom_node_id == backend_id and not node.ignored and node.name:
            return clean(str(node.name.value or ""))
    return ""
