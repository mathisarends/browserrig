"""uv run --env-file .env --extra openai python -m examples.figma_agent --url URL"""

import argparse
import asyncio
import os

from harnessed import Agent, PolicyDecision
from harnessed.plugins import Approvals, LatestObservationOnly
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import (
    Actions,
    Activity,
    CanvasCapture,
    CanvasReady,
    CanvasRegion,
    CanvasRenderer,
    Chrome,
    DocumentReadiness,
    ImageContext,
    KeyboardTools,
    LaunchBrowser,
    NavigationTools,
    Observe,
    ObserveAfterInput,
    PointerTools,
    Readiness,
    ReadinessOptions,
    Recording,
    RecordingOptions,
    Screenshots,
    ScreenshotTrigger,
    TabTools,
)
from browserrig.tools import DialogTools


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visual automation of a Figma prototype in canvas mode"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--selector", default="canvas")
    parser.add_argument("--task", default="Inspect the visible screen and describe its controls.")
    parser.add_argument("--record", action="store_true")
    parser.add_argument(
        "--screenshot-trigger",
        type=ScreenshotTrigger,
        choices=list(ScreenshotTrigger),
        default=ScreenshotTrigger.EACH_STEP,
    )
    parser.add_argument("--keep-latest-n-screenshots", type=int, default=3)
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY first")
    plugins = [
        Chrome(LaunchBrowser(url=args.url)),
        Readiness(
            initial=DocumentReadiness(
                CanvasReady(
                    selector=args.selector,
                    options=ReadinessOptions(canvas_timeout=30),
                )
            ),
            ongoing=DocumentReadiness(
                CanvasReady(
                    selector=args.selector,
                    options=ReadinessOptions(timeout=2),
                )
            ),
        ),
        Observe(
            capture=CanvasCapture(region=CanvasRegion(selector=args.selector)),
            renderer=CanvasRenderer(),
            screenshots=Screenshots(trigger=args.screenshot_trigger),
        ),
        ImageContext(keep_latest_n_screenshots=args.keep_latest_n_screenshots),
        Actions(chain_policy=ObserveAfterInput()),
        PointerTools(),
        KeyboardTools(),
        NavigationTools(),
        TabTools(),
        DialogTools(),
        Activity(),
        LatestObservationOnly(),
        Approvals(default=PolicyDecision.ALLOW),
    ]
    if args.record:
        plugins.append(Recording(RecordingOptions()))
    agent = Agent(
        model=OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra")),
        plugins=plugins,
    )
    print((await agent.run(args.task, max_steps=10)).text)


if __name__ == "__main__":
    asyncio.run(main())
