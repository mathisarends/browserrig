import asyncio
from collections.abc import Awaitable, Callable

from cdpify import CdpSession
from cdpify.exceptions import CDPCommandError


class Worlds:
    """Document-scoped isolated contexts shared by successive frame discoveries."""

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str, str], int] = {}
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
        return await operation(await self.context(cdp, frame_id, document_id))

    async def context(self, cdp: CdpSession, frame_id: str, document_id: str) -> int:
        key = (cdp.session_id, frame_id, document_id)
        async with self._lock:
            if key in self._ids:
                return self._ids[key]
            generation = self._generation
            result = await cdp.page.create_isolated_world(
                frame_id=frame_id, world_name="browserrig"
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
            if not (
                (session_id is None or key[0] == session_id)
                and (frame_id is None or key[1] == frame_id)
                and (context_id is None or value == context_id)
            )
        }
