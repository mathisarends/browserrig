# Harnessed feedback

## 2026-10-29 — 0.2.0: missing required plugin services are silent at the Agent boundary

Status: reproduced offline with the installed `harnessed==0.2.0` release.
This is a diagnostic/API improvement request. Deferred dependencies are explicitly
supported by `Context.install`; the observation alone does not establish a kernel bug.

An `Agent` can open a session and return a successful model answer while a configured
plugin remains unmounted because its required `Inject[T]` service is unavailable.
The reproduction below completes without a missing-dependency exception or warning.

```python
import asyncio

from harnessed import Agent, Inject, Plugin
from harnessed.testing import ScriptedModel

mounted = []


class RequiredService:
    pass


class RequiredFeature(Plugin):
    service: Inject[RequiredService]

    async def setup(self):
        mounted.append(True)


async def main():
    agent = Agent(model=ScriptedModel(["ok"]), plugins=[RequiredFeature()])
    async with agent.session() as session:
        result = await session.run("Run with the configured capability")
        print("result:", result.text)
        print("required feature mounted:", bool(mounted))


asyncio.run(main())
```

Observed output:

```text
result: ok
required feature mounted: False
```

`harnessed/agent.py` installs plugins with `settle=True` and the default
`strict=False`. `harnessed/kernel/context.py` deliberately retains unresolved
plugins in a waiting state. Settling reports setup failures but does not reject
this missing-service case. `Agent` does not expose the installation's `strict`
option through its constructor or `session()` signature.

In a browser integration, a composition mistake can therefore look like a working
agent even though the intended hooks or tools were never mounted. A later lookup
or assertion in application code then reveals the missing capability instead of
an SDK diagnostic naming the plugin and service.

Suggested improvement: expose an Agent-level validation option, or emit a
structured diagnostic listing unresolved plugins and their missing services before
the first model request. Validate after session-scoped services such as `SessionLog`
and `Session` have been published; strict validation at the initial installation
point would reject legitimate plugins waiting for those services. Preserve the
kernel's intentional support for services that can be added later.

The Browserrig migration uses complete compositions and passes all 146 tests,
including the Chrome integration suite. No upstream dependency was patched.
