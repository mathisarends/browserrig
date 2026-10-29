"""uv run --env-file .env --extra openai python -m examples.figma_agent --url URL"""

import argparse
import asyncio
import os

from harnessed import Agent, PolicyDecision
from harnessed.models import PydanticAIModel
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import FigmaMode, LaunchBrowser, RecordingOptions, browser_plugins


async def main() -> None:
    parser = argparse.ArgumentParser(description="Visual browser automation in explicit Figma mode")
    parser.add_argument("--url", required=True)
    parser.add_argument("--selector", default="canvas")
    parser.add_argument("--task", default="Inspect the visible screen and describe its controls.")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY first")
    async with OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra")) as openai:
        agent = Agent(
            model=PydanticAIModel(openai),
            plugins=[
                *browser_plugins(
                    LaunchBrowser(url=args.url),
                    mode=FigmaMode(selector=args.selector),
                    recording=RecordingOptions() if args.record else None,
                ),
                Approvals(default=PolicyDecision.ALLOW),
            ],
        )
        print((await agent.run(args.task, max_steps=10)).text)


if __name__ == "__main__":
    asyncio.run(main())
