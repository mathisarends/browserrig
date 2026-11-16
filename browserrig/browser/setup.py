from typing import Protocol, runtime_checkable

from cdpify import CdpSession


@runtime_checkable
class SessionSetup(Protocol):
    """Configure each newly attached page or out-of-process frame CDP session."""

    async def apply(  # pylint: disable=unused-argument
        self, cdp: CdpSession, *, frame: bool
    ) -> None:
        """Configure `cdp` before use; `frame` marks an out-of-process frame session."""
