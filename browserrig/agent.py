from collections.abc import Iterable

import harnessed
from harnessed import Plugin, PluginValidation, SystemPrompt
from harnessed.kernel import PluginLike
from harnessed.models import Model

from .browser import BrowserOptions
from .composition import browser_plugins

DEFAULT_PROMPT = "Complete the requested browser task using the observed page state."


class Agent(harnessed.Agent):
    """A harnessed agent with browserrig's default browser plugins.

    `plugins` replace the defaults they match and add the rest, and `without`
    drops defaults by type; see `browser_plugins`. Explicit provider clients
    remain caller-owned. Conversations stay in memory; continue one by passing a
    saved `SessionState` to `run` or `session`. Long runs summarize older steps
    once the request fills 80% of the model's context window, or 100k tokens when
    the model reports none; pass `without=(Compaction,)` to keep everything, or a
    configured `Compaction`. Input is paced like a person and streamed for people
    watching; pass `without=(Pacing, Choreography)` to work at full speed unseen.
    """

    def __init__(
        self,
        *,
        model: Model | str | None = None,
        browser: BrowserOptions | None = None,
        plugins: Iterable[PluginLike | None] = (),
        without: Iterable[type[Plugin]] = (),
        system_prompt: str | SystemPrompt | None = DEFAULT_PROMPT,
        plugin_validation: PluginValidation = PluginValidation.ERROR,
    ) -> None:
        super().__init__(
            model=model,
            system_prompt=system_prompt,
            plugins=browser_plugins(*plugins, browser=browser, without=without),
            plugin_validation=plugin_validation,
        )
