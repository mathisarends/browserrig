"""uv run --env-file .env --extra openai python -m examples.controls"""

import argparse
import asyncio
import os

from harnessed import PolicyDecision
from harnessed.models import UserMessage
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import Agent, Chrome


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Native Harnessed steering, pause and resume"
    )
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--task", default="Inspect the page and describe it.")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY first")
    agent = Agent(
        model=OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra")),
        browser=Chrome.launch(url=args.url),
        plugins=[Approvals(default=PolicyDecision.ALLOW)],
    )
    async with agent.session() as session:
        handle = await session.submit(args.task)
        await session.pause()  # Wait for the current complete step, if already running.
        print("Paused:", session.status)
        await session.inbox.steer(
            "Pay particular attention to the navigation and contact information."
        )
        await session.append_message(UserMessage("Do not submit forms."))
        await session.resume()
        print((await handle.result()).text)
        # Also available: await session.stop() and await session.abort().


if __name__ == "__main__":
    asyncio.run(main())
