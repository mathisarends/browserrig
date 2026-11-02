from collections.abc import Iterable
from dataclasses import dataclass

from harnessed import Kit, Plugin, PluginOrder, PromptFormat, SystemPrompt
from harnessed.core.composition import compose_plugins
from harnessed.kernel import PluginLike
from harnessed.plugins import Compaction as ContextCompaction
from harnessed.plugins import ContextState

from .activity import Activity
from .browser import BrowserOptions, Chrome
from .choreography import InputVisualization, TabStrip
from .nudges import Nudges
from .observation import ImageContext, Observe
from .pacing import InputPacing
from .readiness import DownloadReadiness, Readiness
from .tools import (
    Actions,
    DialogTools,
    FileTools,
    FindTools,
    FormTools,
    JavaScriptTools,
    KeyboardTools,
    NavigationTools,
    PointerTools,
    TabTools,
)


def browser_plugins(
    *plugins: PluginLike | Kit | None,
    browser: BrowserOptions | None = None,
    without: Iterable[type[Plugin]] = (),
) -> list[PluginLike]:
    """The default browser agent plugins, adjusted by `plugins` and `without`.

    A plugin that fills the same slot as a default
    replaces it in place, such as `Observe(...)`, `Readiness(...)` or
    `ContextCompaction(...)`; any other plugin is added. `without` drops defaults by type,
    such as `(FileTools,)` for an agent without local files. `None`
    entries are skipped, so optional plugins can be written inline.
    """
    kit = browser_kit(browser=browser).without(*without)
    # The flat API leaves prompt configuration to its caller.
    defaults = Kit(kit.name, plugins=kit.plugins)
    return list(compose_plugins([defaults, *plugins]).plugins)


def browser_kit(*, browser: BrowserOptions | None = None) -> Kit:
    """Browser defaults with Markdown instructions in configured plugin-list order."""
    return Kit(
        name="browserrig",
        plugins=[
            Activity(),
            Chrome(browser),
            # Types and moves the pointer at a person's pace.
            InputPacing(),
            # Streams input and browser UI for anyone watching the session.
            InputVisualization(),
            # Titles and favicons for a viewer's tab strip; the agent reads tabs without it.
            TabStrip(),
            Readiness(),
            DownloadReadiness(),
            Nudges(),
            Observe(),
            ImageContext(),
            # Explain screenshot coordinates before the chains that refer to them.
            # Harnessed resolves setup dependencies independently of prompt order.
            PointerTools(),
            Actions(),
            NavigationTools(),
            JavaScriptTools(),
            KeyboardTools(),
            FormTools(),
            TabTools(),
            DialogTools(),
            FindTools(),
            FileTools(),
            ContextCompaction(trigger=WindowRatio()),
        ],
        prompt=SystemPrompt.from_plugins(
            order=PluginOrder.AS_LISTED,
            format=PromptFormat.MARKDOWN,
        ),
    )


@dataclass(frozen=True)
class WindowRatio:
    """Compact at a share of the context window, or at a token count when it is unknown.

    Many providers report no window, so a plain ratio trigger would never fire for them.
    """

    at: float = 0.8
    fallback_tokens: int = 100_000

    def __call__(self, state: ContextState) -> bool:
        if state.ratio is None:
            return state.input_tokens + state.reserve_tokens >= self.fallback_tokens
        return state.ratio >= self.at
