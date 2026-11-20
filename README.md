# BrowserRig

BrowserRig is a composable Python SDK for agents that operate a browser. A browser
task works like a game. Give the agent a goal, a view of the current state and a
set of moves. After a move, the agent sees what changed and can act again or
answer.

[Harnessed](https://github.com/mathisarends/harnessed) runs that loop and owns the
session. BrowserRig plugins supply the browser, observations and actions. The
plugin list is where you choose what the agent sees and what it can do.

## Compose a browser agent

This agent plays a small game. It clicks the beacon on a
[local page](examples/signal_station.html) and reports the code that appears.
The example requires BrowserRig 0.10 or newer with the `openai` extra,
Python 3.12 or newer, Chrome or Chromium, and `OPENAI_API_KEY`. The page path
is relative to the repository root.

```python
import asyncio
from pathlib import Path

from harnessed import Agent, Approvals

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
    Targeting,
)

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
agent = Agent(
    model="openai-responses:gpt-6.1-terra",
    plugins=plugins,
    approvals=Approvals(allow=[ReferencePointerTools.click]),
)


async def main() -> None:
    async with agent.session() as session:
        browser = session.scope[Browser]
        await browser.tabs.open(Path("examples/signal_station.html"))
        result = await session.run(
            "Activate the beacon and report the signal code shown on the page.",
            max_steps=4,
        )
        print(result.text)


asyncio.run(main())
```

`Runtime` provides shared coordination. `Chrome` and `InputRuntime` give the
session a browser and input devices. `PageReadiness` checks whether the page is
ready to observe. `DomPage` supplies page text and control references to
`BrowserPerception`.
When the model calls `click(ref=...)`, `Actions` coordinates the operation and
`Targeting` resolves the reference in the live page. The next observation shows
the code after the click. The approval policy permits only the click tool.

The [executable example](examples/signal_station.py) also runs this composition
with a scripted model that reads the real observations. It prints the observed
button reference, the click and the resulting code without provider credentials.

## Add screenshots

Add these plugins to the list before constructing `Agent`.

```python
from browserrig import Screenshots, ScreenshotTrigger, SetOfMarks

plugins.extend(
    [
        Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
        SetOfMarks(),
    ]
)
```

The model now receives screenshots alongside page text. `SetOfMarks` labels
visible controls with the same references the model can pass to `click`. Change
the capture policy to control when images enter the model context. See
[observation settings](docs/browser-composition.md#browser-observations).

## Add keyboard input

Give the agent a second way to activate the beacon. Add `KeyboardTools` before
constructing `Agent` and include `send_keys` in the allowlist.

```python
from browserrig import KeyboardTools

plugins.append(KeyboardTools())
approvals = Approvals(allow=[ReferencePointerTools.click, KeyboardTools.send_keys])
```

Pass `approvals=approvals` to `Agent` and change the task to “Activate the
beacon using Tab and Enter, then report the signal code.” The agent can now
send keys to move focus and activate the focused button. It reads the result
through the same observation plugins.

For a longer task with navigation and tab tools, see the
[research example](docs/examples.md#research-a-live-site).

## Documentation

- [Composition](docs/browser-composition.md) covers plugin dependencies, custom
  page models and tools. It also shows the standard `browserrig.Agent` recipe.
- [Runnable examples](docs/examples.md) cover a local task, live research,
  session persistence and tracing.
- The [documentation index](docs/index.md) connects the SDK guides for sessions,
  browser controls, files, events and viewer integration.
- The [changelog](CHANGELOG.md) covers releases and compatibility.

BrowserRig is early 0.x software. CI covers Python 3.12–3.14 on Windows and
Linux. [MIT license](LICENSE).
