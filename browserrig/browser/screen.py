import base64

from cdpify import CdpSession


class ScreenRecorder:
    """Native screen recording of one tab, read back as a byte stream."""

    def __init__(self, cdp: CdpSession) -> None:
        self._cdp = cdp

    async def start(self, *, max_width: int, max_height: int, frame_rate: int) -> str:
        """Start recording and return the stream handle Chrome writes into."""
        result = await self._cdp.page.start_screen_recording(
            audio=False, max_width=max_width, max_height=max_height, frame_rate=frame_rate
        )
        return result.stream

    async def stop(self) -> str:
        """Stop recording and return the stream handle holding the finished video."""
        return (await self._cdp.page.stop_screen_recording()).stream

    async def read(self, stream: str, size: int = 64 * 1024) -> tuple[bytes, bool]:
        """Read the next chunk; the flag is True once the stream is exhausted."""
        chunk = await self._cdp.io.read(handle=stream, size=size)
        data = (
            base64.b64decode(chunk.data, validate=True)
            if chunk.base64_encoded
            else chunk.data.encode("utf-8")
        )
        return data, chunk.eof

    async def close(self, stream: str) -> None:
        await self._cdp.io.close(handle=stream)
