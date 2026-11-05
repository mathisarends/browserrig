"""Record an input walkthrough and a gallery of native Chrome screenshots.

Run `python -m examples.visualization --headed` to watch the same browser live.
"""

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from harnessed.testing import ScriptedModel

from browserrig import (
    Agent,
    Browser,
    Chrome,
    FileSystemOptions,
    IframeRenderer,
    InputVisualization,
    VideoRecording,
    Viewport,
)

from .visualization_gallery import render_gallery
from .visualization_run import VisualWalkthrough
from .visualization_server import visualization_site


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--directory", type=Path, default=Path(".browserrig/visualization")
    )
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--layout", choices=("de", "en"), default="de")
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    renderer = IframeRenderer(keyboard_layout=args.layout, theme=args.theme)
    with visualization_site(directory, args.theme) as url:
        agent = Agent(
            model=ScriptedModel([]),
            browser=Chrome.launch(
                url=url,
                headless=not args.headed,
                viewport=Viewport(width=1440, height=1000),
                files=FileSystemOptions(directory=directory / "workspace"),
            ),
            plugins=[
                InputVisualization(renderer=renderer),
                VideoRecording(directory / "recording", width=1440, height=1000),
            ],
        )
        async with agent.session() as session:
            walkthrough = VisualWalkthrough(
                session.ctx[Browser], session.ctx, directory, url
            )
            await walkthrough.run()
            result = await session.ctx[VideoRecording].finish()
        shutil.copyfile(result.path, directory / "demo.mp4")
        compact = Agent(
            model=ScriptedModel([]),
            browser=Chrome.launch(
                url=url,
                headless=not args.headed,
                viewport=Viewport(width=360, height=740),
            ),
            plugins=[InputVisualization(renderer=renderer)],
        )
        async with compact.session() as session:
            small = VisualWalkthrough(session.ctx[Browser], session.ctx, directory, url)
            await small.compact()
        shots = walkthrough.shots + small.shots
        (directory / "manifest.json").write_text(
            json.dumps(shots, indent=2), encoding="utf-8"
        )
        await render_gallery(directory, url, shots, layout=args.layout)
    print(f"Overview: {directory / 'overview.png'}")
    print(f"Video: {directory / 'demo.mp4'}")
    print(f"Clean observation: {directory / 'observation.png'}")


if __name__ == "__main__":
    asyncio.run(main())
