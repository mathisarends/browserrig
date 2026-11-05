import asyncio
from base64 import b64decode
from pathlib import Path
from time import monotonic

from cdpify import CdpSession
from cdpify.exceptions import CDPCommandError

from browserrig.browser import Tab
from browserrig.core import BrowserError

from .models import Segment


class Capture:
    """One native Page recording, stopped and downloaded before its tab closes."""

    def __init__(self, tab: Tab, path: Path) -> None:
        self.tab = tab
        self.path = path
        self.started_at = 0.0
        self._stream: str | None = None

    async def start(self, *, width: int, height: int, frame_rate: int) -> None:
        self.started_at = monotonic()
        try:
            result = await self.tab.cdp.page.start_screen_recording(
                audio=False,
                max_width=width,
                max_height=height,
                frame_rate=frame_rate,
            )
        except CDPCommandError as error:
            raise BrowserError(
                f"Cannot start video recording: {error.message}. "
                "Page.startScreenRecording requires a Chrome version "
                "that supports this experimental command."
            ) from error
        self._stream = result.stream

    async def stop(self) -> Segment:
        ended_at = monotonic()
        try:
            result = await self.tab.cdp.page.stop_screen_recording()
            self._stream = result.stream
            await _download(self.tab.cdp, self._stream, self.path)
        finally:
            if self._stream is not None:
                await self.tab.cdp.io.close(handle=self._stream)
                self._stream = None
        return Segment(self.path, self.tab.id, self.started_at, ended_at)


async def _download(cdp: CdpSession, stream: str, path: Path) -> None:
    with path.open("wb") as output:
        while True:
            chunk = await cdp.io.read(handle=stream, size=1024 * 1024)
            data = (
                b64decode(chunk.data) if chunk.base64_encoded else chunk.data.encode()
            )
            await asyncio.to_thread(output.write, data)
            if chunk.eof:
                break
