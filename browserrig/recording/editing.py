import asyncio
import json
import math
import os
import subprocess
from pathlib import Path

from browserrig.core import BrowserError

from .models import RecordingResult, Segment, Span

_ENCODING = (
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "fast",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
)


async def edit_video(
    segments: tuple[Segment, ...],
    spans: tuple[tuple[Span, ...], ...],
    *,
    directory: Path,
    ffmpeg: str,
    width: int,
    height: int,
    frame_rate: int,
) -> RecordingResult:
    """Normalize VFR captures, then write the cut and the uncut film in one pass.

    Still frames are retained during work. The uncut film joins every capture in
    order without removing waits.
    """
    graph = []
    labels = []
    originals = []
    manifest = []
    duration = 0.0
    for index, (segment, windows) in enumerate(zip(segments, spans, strict=True)):
        manifest.append(
            {
                "source": segment.path.name,
                "target_id": segment.target_id,
                "started_at": segment.started_at,
                "ended_at": segment.ended_at,
                "kept": [[span.start, span.end] for span in windows],
            }
        )
        length = segment.ended_at - segment.started_at
        branches = "".join(f"[s{index}_{n}]" for n in range(len(windows) + 1))
        graph.append(
            f"[{index}:v]setpts=PTS-STARTPTS,fps={frame_rate},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={length:.9f},"
            f"split={len(windows) + 1}{branches}"
        )
        graph.append(
            f"[s{index}_{len(windows)}]trim=end_frame="
            f"{max(1, math.ceil(length * frame_rate))},setpts=PTS-STARTPTS[o{index}]"
        )
        originals.append(f"[o{index}]")
        for number, window in enumerate(windows):
            label = f"v{len(labels)}"
            start_frame = math.floor(window.start * frame_rate)
            end_frame = max(start_frame + 1, math.ceil(window.end * frame_rate))
            graph.append(
                f"[s{index}_{number}]trim=start_frame={start_frame}:"
                f"end_frame={end_frame},setpts=PTS-STARTPTS[{label}]"
            )
            labels.append(f"[{label}]")
            duration += (end_frame - start_frame) / frame_rate
    (directory / "timeline.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    if not labels:
        raise BrowserError("The recording contains no retained video intervals")
    graph.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[out]")
    graph.append("".join(originals) + f"concat=n={len(originals)}:v=1:a=0[full]")
    script = directory / "edit.ffgraph"
    script.write_text(";\n".join(graph), encoding="utf-8")
    path = directory / "video.mp4"
    original_path = directory / "original.mp4"
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for segment in segments:
        command.extend(["-i", str(segment.path)])
    command.extend(["-filter_complex_script", str(script)])
    for label, output in (("[out]", path), ("[full]", original_path)):
        command.extend(["-map", label, *_ENCODING, str(output)])
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        _, errors = await process.communicate()
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise BrowserError(f"Video editing failed: {errors.decode(errors='replace')}")
    return RecordingResult(
        path=path,
        original_path=original_path,
        sources=tuple(segment.path for segment in segments),
        original_duration=sum(s.ended_at - s.started_at for s in segments),
        duration=duration,
    )
