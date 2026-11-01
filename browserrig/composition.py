from collections.abc import Iterable
from dataclasses import dataclass

from harnessed import Kit, Plugin
from harnessed.core.composition import compose_plugins
from harnessed.kernel import PluginLike
from harnessed.plugins import Compaction, ContextState

from .activity import Activity
from .browser import BrowserOptions, Chrome
from .choreography import Choreography, TabStrip
from .nudges import Nudges
from .observation import ImageContext, Observe
from .pacing import Pacing
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
    `Compaction(...)`; any other plugin is added. `without` drops defaults by type,
    such as `(FileTools,)` for an agent without local files. `None`
    entries are skipped, so optional plugins can be written inline.
    """
    kit = browser_kit(browser=browser).without(*without)
    return list(compose_plugins([kit, *(p for p in plugins if p is not None)]).plugins)


def browser_kit(*, browser: BrowserOptions | None = None) -> Kit:
    """Browser defaults as a native Harnessed kit, with explicit instruction ordering."""
    return Kit(
        "browserrig",
        [
            Activity(),
            Chrome(browser),
            # Types and moves the pointer at a person's pace.
            Pacing(),
            # Streams input and browser UI for anyone watching the session.
            Choreography(),
            # Titles and favicons for a viewer's tab strip; the agent reads tabs without it.
            TabStrip(),
            Readiness(),
            DownloadReadiness(),
            Nudges(),
            Observe(),
            ImageContext(),
            Actions(),
            NavigationTools(),
            JavaScriptTools(),
            KeyboardTools(),
            PointerTools(),
            FormTools(),
            TabTools(),
            DialogTools(),
            FindTools(),
            FileTools(),
            Compaction(trigger=WindowRatio()),
        ],
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
