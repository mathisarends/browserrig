"""uv run --extra openai python -m examples.openai_agent --headed"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from harnessed import PolicyDecision
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import BrowserAgent, DomMode, LaunchBrowser, RecordingOptions, TerminalEvents

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
    parser.add_argument("--quiet", action="store_true", help="Disable JSON event output on stderr")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in the environment or in .env")

    agent = BrowserAgent(
        model=OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra")),
        browser=LaunchBrowser(url=args.url, headless=not args.headed),
        mode=DomMode(),
        recording=RecordingOptions() if args.record else None,
        session_directory=Path(".browserrig/sessions-v2"),
        approvals=Approvals(default=PolicyDecision.ALLOW),
        plugins=[] if args.quiet else [TerminalEvents()],
    )
    async with agent.session() as session:
        result = await session.run(args.task, max_steps=20, token_budget=80000)
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
