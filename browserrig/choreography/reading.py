"""A bounded native page-reading pass, owned by the tool's presentation lifetime."""

import asyncio
import logging
from contextlib import suppress

from cdpify import CDPCommandError

from browserrig.browser import Tab
from browserrig.core import BrowserError
from browserrig.scripts import READING_SCROLL, ReadingScrollArgs

from .events import ReadingSweepEvent

logger = logging.getLogger(__name__)


async def sweep(tab: Tab, *, work_id: str, document_id: str) -> None:
    if not _available(tab, document_id):
        return
    try:
        frame = await tab.main_frame()
        async with asyncio.timeout(1):
            movable = await frame.run(
                READING_SCROLL, ReadingScrollArgs(operation="measure")
            )
        if not movable or not _available(tab, document_id):
            return
        args = ReadingScrollArgs(operation="sweep")
        try:
            await tab.emit(
                ReadingSweepEvent(
                    work_id=work_id, down=args.down, hold=args.hold, back=args.back
                )
            )
            async with asyncio.timeout(args.down + args.hold + args.back + 1):
                if _available(tab, document_id):
                    await frame.run(READING_SCROLL, args)
        finally:
            if _available(tab, document_id):
                with suppress(BrowserError, CDPCommandError, TimeoutError):
                    async with asyncio.timeout(1):
                        await frame.run(
                            READING_SCROLL, ReadingScrollArgs(operation="cancel")
                        )
            tab.layout_changed()
    except (BrowserError, CDPCommandError, TimeoutError):
        # A failed presentation must not discard a successfully saved extraction.
        logger.debug("Page reading choreography unavailable")


def _available(tab: Tab, document_id: str) -> bool:
    return (
        not tab.closed
        and not tab.navigation_pending
        and tab.dialog is None
        and tab.document_id == document_id
    )
