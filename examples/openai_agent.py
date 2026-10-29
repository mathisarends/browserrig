"""uv run --env-file .env --extra openai python -m examples.openai_agent --headed"""

import argparse
import asyncio
import os
from pathlib import Path

from harnessed import Agent, PolicyDecision
from harnessed.models import PydanticAIModel
from harnessed.plugins import Approvals, JsonlSessions
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import LaunchBrowser, RecordingOptions, WebMode, browser_plugins

DEFAULT_TASK = (
    "Erkunde das Voyager-Programm. Vergleiche Voyager 1 und Voyager 2 nach Startdatum, "
    "besuchten Planeten und jeweils einer wissenschaftlichen Entdeckung. Öffne passende "
    "Detailartikel in neuen Tabs. Finde außerdem drei ungewöhnliche Inhalte der Voyager "
    "Golden Record. Liefere eine kompakte Vergleichstabelle und belege die Ergebnisse mit "
    "den besuchten Quellen-URLs."
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Browser automation using OpenAI's Responses API")
    parser.add_argument("--url", default="https://de.wikipedia.org/wiki/Voyager-Programm")
    parser.add_argument(
        "--task", default=DEFAULT_TASK, help="Override the Voyager research mission"
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in the environment or use uv run --env-file .env")

    # OpenAIResponsesModel reads OPENAI_API_KEY. Harnessed adapts its native model;
    # activity tracking observes events and never wraps or decorates this object.
    async with OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra")) as openai:
        agent = Agent(
            model=PydanticAIModel(openai),
            instructions="Complete the requested browser task using the observed page state.",
            plugins=[
                *browser_plugins(
                    LaunchBrowser(url=args.url, headless=not args.headed),
                    mode=WebMode(screenshots=True),
                    recording=RecordingOptions() if args.record else None,
                ),
                JsonlSessions(Path(".browserrig/sessions")),
                Approvals(default=PolicyDecision.ALLOW),
            ],
        )
        async with agent.session() as session:
            result = await session.run(args.task, max_steps=20, token_budget=80000)
            print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
