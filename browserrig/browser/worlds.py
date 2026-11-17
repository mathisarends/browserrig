import asyncio
from collections.abc import Awaitable, Callable
from typing import NamedTuple

from cdpify import CDPCommandError, CdpSession

# Runtime bindings target browserrig's isolated worlds by this name.
WORLD_NAME = "browserrig"


class _WorldKey(NamedTuple):
    session_id: str
    frame_id: str
    document_id: str


class Worlds:
    """Document-scoped isolated contexts shared by successive frame discoveries."""

    def __init__(self) -> None:
        self._ids: dict[_WorldKey, int] = {}
        self._generation = 0
        self._lock = asyncio.Lock()

    async def run[T](
        self,
        cdp: CdpSession,
        frame_id: str,
        document_id: str,
        operation: Callable[[int], Awaitable[T]],
        *,
        retry: bool = True,
    ) -> T:
        context = await self.context(cdp, frame_id, document_id)
        try:
            return await operation(context)
        except CDPCommandError as error:
            # Only a context rejected before execution is safe to retry.
            if not retry or "cannot find context" not in error.message.lower():
                raise
            self.invalidate(session_id=cdp.session_id, frame_id=frame_id)
        context_id = await self.context(cdp, frame_id, document_id)
        return await operation(context_id)

    async def context(self, cdp: CdpSession, frame_id: str, document_id: str) -> int:
        key = _WorldKey(cdp.session_id, frame_id, document_id)
        async with self._lock:
            if key in self._ids:
                return self._ids[key]
            generation = self._generation
            result = await cdp.page.create_isolated_world(
                frame_id=frame_id, world_name=WORLD_NAME
            )
            if generation == self._generation:
                self._ids[key] = result.execution_context_id
            return result.execution_context_id

    def invalidate(
        self,
        *,
        session_id: str | None = None,
        frame_id: str | None = None,
        context_id: int | None = None,
    ) -> None:
        self._generation += 1
        self._ids = {
            key: value
            for key, value in self._ids.items()
            if not _matches_world(
                key,
                value,
                session_id=session_id,
                frame_id=frame_id,
                context_id=context_id,
            )
        }


def _matches_world(
    key: _WorldKey,
    value: int,
    *,
    session_id: str | None,
    frame_id: str | None,
    context_id: int | None,
) -> bool:
    return (
        (session_id is None or key.session_id == session_id)
        and (frame_id is None or key.frame_id == frame_id)
        and (context_id is None or value == context_id)
    )
