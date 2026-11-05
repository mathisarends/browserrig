import asyncio
import math
import shutil
from pathlib import Path
from uuid import uuid4

from harnessed import Context, Plugin, hook
from harnessed.kernel import dependency

from browserrig.activity import Activity
from browserrig.browser import Browser
from browserrig.core import BrowserError
from browserrig.events import TabActivatedEvent, TabClosingEvent

from .capture import Capture
from .editing import edit_video
from .models import RecordingResult, Segment, Span
from .timeline import kept_spans


class VideoRecording(Plugin, slot="browserrig.recording", provides=True):
    """Record the active page and remove Activity's model, compaction and pause waits.

    Each mount creates its own directory. Native captures and a cut manifest are
    retained alongside video.mp4. FFmpeg must be available when the session opens.
    """

    _browser = dependency(Browser)
    _activity = dependency(Activity)

    def __init__(
        self,
        directory: Path = Path(".browserrig/recordings"),
        *,
        width: int = 1280,
        height: int = 800,
        frame_rate: int = 30,
        padding: float = 0.15,
        ffmpeg: str = "ffmpeg",
    ) -> None:
        super().__init__()
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError("Video width and height must be positive even integers")
        if not 1 <= frame_rate <= 60:
            raise ValueError("Video frame_rate must be between 1 and 60")
        if not math.isfinite(padding) or padding < 0:
            raise ValueError("Video padding must be finite and nonnegative")
        self.directory = Path(directory)
        self.width = width
        self.height = height
        self.frame_rate = frame_rate
        self.padding = padding
        self.ffmpeg = ffmpeg
        self.result: RecordingResult | None = None
        self.output_directory: Path | None = None
        self._capture: Capture | None = None
        self._segments: list[Segment] = []
        self._lock = asyncio.Lock()
        self._finish_task: asyncio.Task[RecordingResult] | None = None
        self._binary = ""

    async def setup(self, ctx: Context) -> None:
        binary = shutil.which(self.ffmpeg)
        if binary is None:
            raise BrowserError("VideoRecording requires FFmpeg on PATH or ffmpeg=...")
        self._binary = binary
        self.output_directory = self.directory.resolve() / uuid4().hex
        await asyncio.to_thread(self.output_directory.mkdir, parents=True)
        await self._activate()
        ctx.effect(self.finish)

    async def finish(self) -> RecordingResult:
        """Stop and edit once; also called automatically before Chrome shuts down."""
        if self._finish_task is None:
            self._finish_task = asyncio.create_task(
                self._finish(), name="browserrig:video"
            )
        return await asyncio.shield(self._finish_task)

    @hook(TabActivatedEvent)
    async def _on_activated(self, _event: TabActivatedEvent) -> None:
        if self._finish_task is None:
            await self._activate()

    @hook(TabClosingEvent)
    async def _on_closing(self, event: TabClosingEvent) -> None:
        async with self._lock:
            if self._capture is not None and self._capture.tab.id == event.target_id:
                await self._stop_capture()

    async def _activate(self) -> None:
        async with self._lock:
            if self._finish_task is not None:
                return
            tab = self._browser.active_tab
            if self._capture is not None and self._capture.tab.id == tab.id:
                return
            await self._stop_capture()
            assert self.output_directory is not None
            capture = Capture(
                tab, self.output_directory / f"{len(self._segments):04d}.mp4"
            )
            await capture.start(
                width=self.width, height=self.height, frame_rate=self.frame_rate
            )
            self._capture = capture

    async def _finish(self) -> RecordingResult:
        async with self._lock:
            await self._stop_capture()
        if not self._segments:
            raise BrowserError("No video was recorded")
        assert self.output_directory is not None
        intervals = self._activity.intervals(now=self._segments[-1].ended_at)
        spans = tuple(
            kept_spans(
                intervals,
                started_at=segment.started_at,
                ended_at=segment.ended_at,
                padding=self.padding,
            )
            for segment in self._segments
        )
        if not any(spans):
            # A session containing only waits still gets a brief view of its final page.
            duration = self._segments[-1].ended_at - self._segments[-1].started_at
            spans = (
                *spans[:-1],
                (Span(max(0, duration - 1 / self.frame_rate), duration),),
            )
        self.result = await edit_video(
            tuple(self._segments),
            spans,
            directory=self.output_directory,
            ffmpeg=self._binary,
            width=self.width,
            height=self.height,
            frame_rate=self.frame_rate,
        )
        return self.result

    async def _stop_capture(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            self._segments.append(await capture.stop())
