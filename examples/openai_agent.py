"""uv run --extra openai python -m examples.openai_agent --headed"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from harnessed import PolicyDecision, SessionState
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals, Compaction
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import (
    BrowserAgent,
    DomMode,
    FileSystemOptions,
    ImageContext,
    LaunchBrowser,
    TerminalEvents,
    UntilCompaction,
)
from examples.telemetry import add_tracing_arguments, tracing_plugins

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
    parser.add_argument(
        "--workspace", type=Path, help="Reuse a directory for agent files and downloads"
    )
    parser.add_argument(
        "--state", type=Path, help="Load and save a conversation snapshot in this JSON file"
    )
    parser.add_argument("--quiet", action="store_true", help="Disable JSON event output on stderr")
    add_tracing_arguments(parser)
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in the environment or in .env")
    state = (
        SessionState.from_json(args.state.read_text(encoding="utf-8"))
        if args.state and args.state.exists()
        else None
    )

    async with tracing_plugins(
        enabled=args.trace,
        capture_content=args.trace_content,
        max_content_length=args.trace_max_content_length,
    ) as telemetry:
        agent = BrowserAgent(
            model=PydanticAIModel(OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))),
            browser=LaunchBrowser(url=args.url, headless=not args.headed),
            mode=DomMode(),
            image_context=ImageContext(UntilCompaction()),
            file_system=FileSystemOptions(directory=args.workspace) if args.workspace else None,
            approvals=Approvals(default=PolicyDecision.ALLOW),
            plugins=[
                Compaction(trigger=lambda state: state.input_tokens >= 32000, keep_steps=4),
                *telemetry,
                *([] if args.quiet else [TerminalEvents()]),
            ],
        )
        async with agent.session(state=state) as session:
            result = await session.run(args.task, max_steps=20, token_budget=80000)
            if args.state:
                args.state.parent.mkdir(parents=True, exist_ok=True)
                pending = args.state.with_suffix(args.state.suffix + ".tmp")
                pending.write_text(result.state.to_json(), encoding="utf-8")
                pending.replace(args.state)
            print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
