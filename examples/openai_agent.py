"""uv run --extra openai python -m examples.openai_agent --headed"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from harnessed import PolicyDecision
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import BrowserAgent, DomMode, LaunchBrowser, RecordingOptions

DEFAULT_TASK = (
    "Erkunde das Voyager-Programm. Vergleiche Voyager 1 und Voyager 2 nach Startdatum, "
    "besuchten Planeten und jeweils einer wissenschaftlichen Entdeckung. Öffne passende "
    "Detailartikel in neuen Tabs. Finde außerdem drei ungewöhnliche Inhalte der Voyager "
    "Golden Record. Liefere eine kompakte Vergleichstabelle und belege die Ergebnisse mit "
    "den besuchten Quellen-URLs."
)


load_dotenv()


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
        parser.error("Set OPENAI_API_KEY in the environment or in .env")

    # The caller owns the provider model; BrowserAgent configures the browser plugins.
    async with OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra")) as openai:
        agent = BrowserAgent(
            model=openai,
            browser=LaunchBrowser(url=args.url, headless=not args.headed),
            mode=DomMode(screenshots=True),
            recording=RecordingOptions() if args.record else None,
            session_directory=Path(".browserrig/sessions"),
            approvals=Approvals(default=PolicyDecision.ALLOW),
        )
        async with agent.session() as session:
            result = await session.run(args.task, max_steps=20, token_budget=80000)
            print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
