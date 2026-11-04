"""uv run python -m examples.session_store --url about:blank"""

import argparse
import asyncio
from pathlib import Path

from harnessed.integrations.json import JsonSessionStore
from harnessed.testing import ScriptedModel

from browserrig import Agent, Chrome, FileSystemOptions


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(".browserrig/persistence-demo")
    )
    parser.add_argument("--id", default="browser-demo")
    parser.add_argument("--url", default="about:blank")
    args = parser.parse_args()

    # Scripted replies keep this persistence example independent of model providers.
    first = Agent(
        model=ScriptedModel(["First page inspected."]),
        store=JsonSessionStore(root=args.root / "sessions"),
        browser=Chrome.launch(
            url=args.url,
            files=FileSystemOptions(directory=args.root / "workspace"),
        ),
    )
    async with first.session(id=args.id) as session:
        print((await session.run("Inspect the page.", max_steps=1)).text)

    # Rebuild the agent/store as a new request would; Chrome also starts fresh.
    second = Agent(
        model=ScriptedModel(["Previous conversation retained; fresh page inspected."]),
        store=JsonSessionStore(root=args.root / "sessions"),
        browser=Chrome.launch(
            url=args.url,
            files=FileSystemOptions(directory=args.root / "workspace"),
        ),
    )
    async with second.session(id=args.id) as session:
        result = await session.run("Continue from the previous answer.", max_steps=1)
        print(f"{session.id}: {result.text}")


if __name__ == "__main__":
    asyncio.run(main())
