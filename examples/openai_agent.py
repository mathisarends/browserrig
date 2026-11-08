"""uv run --extra openai python -m examples.openai_agent --headed"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from harnessed import PolicyDecision
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import (
    Agent,
    Chrome,
    Done,
    Files,
    ImageContext,
    LocalWorkspace,
    TerminalEvents,
    UntilCompaction,
    VideoRecording,
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
    parser = argparse.ArgumentParser(
        description="Browser automation using OpenAI's Responses API"
    )
    parser.add_argument(
        "--url", default="https://de.wikipedia.org/wiki/Voyager-Programm"
    )
    parser.add_argument(
        "--task", default=DEFAULT_TASK, help="Override the Voyager research mission"
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--video",
        type=Path,
        help="Record into this directory and cut model waits at session exit (FFmpeg required)",
    )
    parser.add_argument(
        "--done",
        action="store_true",
        help="Require done before the final answer; allow standalone progress messages",
    )
    parser.add_argument(
        "--workspace", type=Path, help="Reuse a directory for agent files and downloads"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Disable JSON event output on stderr"
    )
    add_tracing_arguments(parser)
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in the environment or in .env")

    async with tracing_plugins(
        enabled=args.trace,
        capture_content=args.trace_content,
        trace_hooks=args.trace_hooks,
        max_content_length=args.trace_max_content_length,
    ) as telemetry:
        agent = Agent(
            model=PydanticAIModel(
                OpenAIResponsesModel(os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
            ),
            browser=Chrome.launch(
                url=args.url,
                headless=not args.headed,
            ),
            plugins=[
                Files(LocalWorkspace(args.workspace)),
                ImageContext(UntilCompaction()),
                VideoRecording(args.video) if args.video is not None else None,
                Approvals(default=PolicyDecision.ALLOW),
                *telemetry,
                Done() if args.done else None,
                None if args.quiet else TerminalEvents(),
            ],
        )
        async with agent.session() as session:
            recording = (
                session.scope[VideoRecording] if args.video is not None else None
            )
            result = await session.run(args.task, max_steps=20)
            print(result.text)
        if recording is not None and recording.result is not None:
            print(f"Video: {recording.result.path}")


if __name__ == "__main__":
    asyncio.run(main())
