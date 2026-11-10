from collections.abc import Iterable

import harnessed
from harnessed import (
    Plugin,
    PluginPack,
    PluginValidation,
    SystemPrompt,
)
from harnessed.kernel import PluginLike
from harnessed.models import Model
from harnessed.sessions import SessionStore

from .browser import Chrome
from .composition import browser_pack

DEFAULT_PROMPT = "Complete the requested browser task using the observed page state."


class Agent(harnessed.Agent):
    """A harnessed agent with browserrig's default browser plugins.

    `plugins` replace the defaults they match and add the rest, and `without`
    drops defaults by type; see `browser_pack`. Explicit provider clients
    remain caller-owned. Pass `browser=Chrome.launch(...)` to start Chrome or
    `browser=Chrome.connect(...)` to use an existing browser when the session opens.
    Conversations stay in memory by default; pass `store`
    to reopen them by ID, or continue with an explicit `SessionState`. Long runs
    summarize older steps once the request fills 80% of the model's context window,
    or 100k tokens when the model reports none. Pass `without=(ContextCompaction,)`
    to keep everything, or a configured `ContextCompaction`. Input is paced like a
    person and streamed for people
    watching; pass `without=(InputPacing, InputVisualization)` to work at full speed unseen.

    The default `TaskMemory` compaction asks for a workspace checkpoint before
    summarizing and an explicit read afterward. Configure `TaskMemory(...)` to
    tune this protocol; plain `ContextCompaction(...)` disables its memory guidance.
    """

    def __init__(
        self,
        *,
        model: Model | str | None = None,
        browser: Chrome | None = None,
        plugins: Iterable[PluginLike | PluginPack | None] = (),
        without: Iterable[type[Plugin]] = (),
        instructions: str | None = DEFAULT_PROMPT,
        prompt: SystemPrompt | None = None,
        store: SessionStore | None = None,
        plugin_validation: PluginValidation = PluginValidation.ERROR,
    ) -> None:
        pack = browser_pack(browser=browser)
        pack = pack.without(*without)
        super().__init__(
            model=model,
            instructions=instructions,
            prompt=prompt,
            plugins=[pack, *plugins],
            store=store,
            plugin_validation=plugin_validation,
        )
