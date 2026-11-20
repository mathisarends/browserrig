# Runnable examples

[Documentation index](index.md) · [Back to README](../README.md)

The browser examples use the repository checkout, Python 3.12 or newer, and
Chrome or Chromium.

## Start with a local task

The [signal station](../examples/signal_station.py) puts together a browser
runtime, DOM observations and clicks by reference. A scripted model reads the
button reference from the first observation and the signal code from the next.
`--screenshots` adds image capture and labels to the same composition.
`--model` lets a provider model choose the move and answer. The
[README tutorial](../README.md#compose-a-browser-agent) walks through the
composition in Python.

## Research a live site

The [research agent](../examples/openai_agent.py) opens pages about the Voyager
program, follows links across tabs and cites visited URLs. It uses the `openai`
extra and `OPENAI_API_KEY`. The `--url` and `--task` options select a different
site and goal. Use `--headed` to watch the run or `--video` with a directory to
record it. Recording requires FFmpeg. See [choreography and video](browser-choreography.md).

## Keep state and inspect behavior

| Example | What it adds |
| --- | --- |
| [Session store](../examples/session_store.py) | Persist a conversation and reopen it by ID |
| [Tracing smoke test](../examples/tracing_smoke.py) | Export traces of an agent turn |
| [Controls](../examples/controls.py) | Pause and resume a running agent |

## Use Chrome directly

[Direct browser access](../examples/direct_browser.py) opens a page and renders
the observation from Python without an agent loop. The
[connection example](../examples/connect_browser.py) attaches to an existing
Chrome instance via CDP. See [browser interaction](browser-interaction.md) for
direct input and tab handling.
