import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager


class BrowserCoordination:
    """Serialize agent actions, observations and human control within one session.

    Acquire once around a complete operation. Calls made within that operation,
    such as an action's capture or readiness check, share its ownership.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @asynccontextmanager
    async def exclusive(self) -> AsyncGenerator[None]:
        """Hold exclusive control until the operation finishes or is cancelled."""
        async with self._lock:
            yield
