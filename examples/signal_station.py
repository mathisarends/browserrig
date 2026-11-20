"""Compose an agent that activates a beacon on a local web page."""

import argparse
import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path

from harnessed import Agent, Approvals
from harnessed.models import (
    ImagePart,
    ImageReference,
    ModelChunk,
    ModelRequest,
    ToolCall,
)
from harnessed.testing import CallbackModel

from browserrig import (
    Actions,
    Browser,
    BrowserPerception,
    Chrome,
    DomPage,
    InputRuntime,
    PageReadiness,
    ReferencePointerTools,
    Runtime,
    Screenshots,
    ScreenshotTrigger,
    SetOfMarks,
    Targeting,
)

PAGE = Path(__file__).with_suffix(".html")
TASK = "Activate the beacon and report the signal code shown on the page."


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--screenshots", action="store_true", help="Capture at each step"
    )
    parser.add_argument(
        "--model", help="Provider model, e.g. openai-responses:gpt-6.1-terra"
    )
    args = parser.parse_args()

    plugins = [
        Runtime(),
        Chrome.launch(),
        InputRuntime(),
        PageReadiness(),
        BrowserPerception(),
        DomPage(),
        Actions(),
        Targeting(),
        ReferencePointerTools(),
    ]
    if args.screenshots:
        plugins.extend([Screenshots(trigger=ScreenshotTrigger.EACH_STEP), SetOfMarks()])
    agent = Agent(
        model=args.model or CallbackModel(play_turn),
        plugins=plugins,
        approvals=Approvals(allow=[ReferencePointerTools.click]),
    )
    async with agent.session() as session:
        await session.scope[Browser].tabs.open(PAGE)
        result = await session.run(TASK, max_steps=4)
    print(result.text)


async def play_turn(request: ModelRequest) -> AsyncIterator[ModelChunk]:
    """Read the browser observation, then click or answer based on its state."""
    if any(
        isinstance(part, ImagePart | ImageReference)
        for message in request.messages
        if isinstance(message.content, tuple)
        for part in message.content
    ):
        print("Model request includes a screenshot.")

    observation = next(
        (
            message.text
            for message in reversed(request.messages)
            if message.text.startswith("# Signal station\n")
        ),
        "",
    )
    if code := re.search(r"Signal code: (\S+)", observation):
        yield ModelChunk(text=f"Signal code: {code[1]}")
        return

    # This fixture has one button. Its reference comes from the current observation.
    button = re.search(r'\[([^\]]+)\] button "Activate beacon"', observation)
    if button is None:
        raise RuntimeError("The observation is missing the beacon button.")
    print(f'Observed [{button[1]}] button "Activate beacon"')
    print(f"Calling click(ref={button[1]!r})")
    yield ModelChunk(tool_call=ToolCall("click", {"ref": button[1]}))


if __name__ == "__main__":
    asyncio.run(main())
