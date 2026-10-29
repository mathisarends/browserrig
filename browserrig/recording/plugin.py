import asyncio
import base64
import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from uuid import uuid4

from harnessed import Context, Inject, Plugin, PluginState, SessionLog, hook
from harnessed.events import AgentControlChangedEvent, ControlState

from browserrig.activity.models import inference_only, project_intervals
from browserrig.browser.base import Browser
from browserrig.browser.tab import Tab
from browserrig.core.errors import RecordingError
from browserrig.core.geometry import Geometry
from browserrig.events import (
    RECORDING_EVENTS,
    ReadyEvent,
    RecordingFailedEvent,
    RecordingFinishedEvent,
    RecordingSegmentClosedEvent,
    RecordingStartedEvent,
)
from browserrig.readiness.plugin import Readiness

from .config import RecordingOptions
from .models import RecordingManifest, RecordingSegment


@dataclass
class _State:
    log_offset: int = 0
    directory: Path | None = None
    tab: Tab | None = None
    stream: str | None = None
    recording_id: str = ""
    started_at: float = 0
    geometry: Geometry | None = None
    paused: bool = False
    failed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    start_task: asyncio.Task[None] | None = None
    segments: list[RecordingSegment] = field(default_factory=list)


class Recording(Plugin, needs=(Browser, SessionLog, Readiness), provides=True):
    events = RECORDING_EVENTS
    _state = PluginState(_State)
    _browser: Inject[Browser]
    _log: Inject[SessionLog]

    def __init__(self, options: RecordingOptions | None = None) -> None:
        super().__init__()
        self.options = options or RecordingOptions()

    async def setup(self, ctx: Context) -> None:
        self._state.log_offset = len(self._log.events)
        self._state.directory = (
            self.options.directory.resolve() / f"{self._log.id}-{self._browser.id[:12]}"
        )
        await asyncio.to_thread(self._state.directory.mkdir, parents=True, exist_ok=False)
        ctx.effect(self._finalize)

    @hook(ReadyEvent)
    async def _on_ready(self, event: ReadyEvent) -> None:
        browser = self._browser
        if event.target_id != browser.active_tab.id or self._state.paused:
            return
        if self._state.start_task is not None and not self._state.start_task.done():
            return
        self._state.start_task = asyncio.create_task(
            self.ensure_started(browser.active_tab), name="browserrig:recording-start"
        )
        self._state.start_task.add_done_callback(_retrieve_failure)

    async def ensure_started(self, tab: Tab, *, geometry: Geometry | None = None) -> None:
        async with self._state.lock:
            if self._state.paused or self._state.failed:
                if self._state.failed and self.options.required:
                    raise RecordingError("Required native recording is unavailable")
                return
            if self._state.tab is tab:
                if geometry is not None:
                    self._state.geometry = geometry
                return
            if self._state.tab is not None:
                await self._stop()
            try:
                async with asyncio.timeout(self.options.timeout):
                    result = await tab.cdp.page.start_screen_recording(
                        audio=False,
                        max_width=self.options.max_width,
                        max_height=self.options.max_height,
                        frame_rate=self.options.frame_rate,
                    )
                self._state.tab, self._state.stream = tab, result.stream
                self._state.geometry = geometry
                self._state.recording_id = uuid4().hex
                self._state.started_at = monotonic()
                await self._browser.emit(
                    RecordingStartedEvent(
                        recording_id=self._state.recording_id,
                        target_id=tab.id,
                        document_id=tab.document_id,
                    )
                )
            except Exception as error:  # pylint: disable=broad-exception-caught
                # Record optional backend failures and enforce required recording in _failed.
                await self._failed(f"Native recording start failed ({type(error).__name__})")

    async def _failed(self, reason: str) -> None:
        self._state.failed = True
        await self._browser.emit(RecordingFailedEvent(reason=reason))
        if self.options.required:
            raise RecordingError(reason)

    async def _stop(self) -> None:
        tab, stream = self._state.tab, self._state.stream
        if tab is None:
            return
        self._state.tab, self._state.stream = None, None
        assert self._state.directory is not None
        partial = self._state.directory / f"{self._state.recording_id}.partial"
        handles = {stream} if stream else set()
        try:
            async with asyncio.timeout(self.options.timeout):
                stopped = await tab.cdp.page.stop_screen_recording()
                handles.add(stopped.stream)
                digest, size = hashlib.sha256(), 0
                output = await asyncio.to_thread(partial.open, "xb")
                try:
                    while True:
                        chunk = await tab.cdp.io.read(handle=stopped.stream, size=64 * 1024)
                        data = (
                            base64.b64decode(chunk.data, validate=True)
                            if chunk.base64_encoded
                            else chunk.data.encode("utf-8")
                        )
                        size += len(data)
                        if size > self.options.max_bytes:
                            raise RecordingError("Native recording exceeds max_bytes")
                        digest.update(data)
                        await _disk(output.write, data)
                        if chunk.eof:
                            break
                    await _disk(output.flush)
                    await _disk(os.fsync, output.fileno())
                finally:
                    await _disk(output.close)
                header = await asyncio.to_thread(_header, partial)
                extension, mime = _container(header)
                target = partial.with_suffix(extension)
                await asyncio.to_thread(partial.replace, target)
                segment = RecordingSegment(
                    id=self._state.recording_id,
                    path=target.name,
                    mime=mime,
                    target_id=tab.id,
                    started_at=self._state.started_at,
                    ended_at=monotonic(),
                    sha256=digest.hexdigest(),
                    size=size,
                    geometry=self._state.geometry,
                )
                self._state.segments.append(segment)
                await self._browser.emit(
                    RecordingSegmentClosedEvent(
                        recording_id=self._state.recording_id,
                        path=str(target),
                        sha256=digest.hexdigest(),
                        started_at=self._state.started_at,
                        size=size,
                        target_id=tab.id,
                    )
                )
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Finalization failures must produce a recording receipt.
            await self._failed(f"Native recording finalization failed ({type(error).__name__})")
        finally:
            for handle in handles:
                with suppress(Exception):
                    async with asyncio.timeout(5):
                        await tab.cdp.io.close(handle=handle)

    @hook(AgentControlChangedEvent)
    async def _on_control(self, event: AgentControlChangedEvent) -> None:
        if self.options.record_during_pause:
            return
        if event.state == ControlState.PAUSED:
            self._state.paused = True
            async with self._state.lock:
                await self._stop()
        elif event.state == ControlState.ACTIVE:
            self._state.paused = False

    async def _finalize(self) -> None:
        if self._state.start_task is not None:
            await asyncio.gather(self._state.start_task, return_exceptions=True)
        async with self._state.lock:
            await self._stop()
            assert self._state.directory is not None
            intervals = project_intervals(self._log.events[self._state.log_offset :])
            payload = RecordingManifest(
                browser_id=self._browser.id,
                segments=tuple(self._state.segments),
                failed=self._state.failed,
                activity=intervals,
                inference_only=inference_only(intervals),
            )
            manifest = self._state.directory / "manifest.json"
            await asyncio.to_thread(_write_manifest, manifest, payload)
            await self._browser.emit(RecordingFinishedEvent(manifest=str(manifest)))


async def _disk(function, *arguments):
    task = asyncio.create_task(asyncio.to_thread(function, *arguments))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def _header(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(32)


def _write_manifest(path: Path, payload: RecordingManifest) -> None:
    temporary = path.with_suffix(".partial")
    temporary.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def _retrieve_failure(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _container(header: bytes) -> tuple[str, str]:
    if header.startswith(b"\x1aE\xdf\xa3"):
        return ".webm", "video/webm"
    if header[4:8] == b"ftyp":
        return ".mp4", "video/mp4"
    raise RecordingError("Native recording returned an unknown video container")
