from collections.abc import Iterable
from dataclasses import dataclass

from harnessed import (
    Plugin,
    PluginPack,
    PluginPackPromptPolicy,
    PromptFormat,
    SystemPrompt,
)
from harnessed.kernel import PluginLike
from harnessed.plugins import Compaction as ContextCompaction
from harnessed.plugins import ContextState

from .activity import Activity
from .browser import Chrome, DownloadReceiving
from .choreography import InputVisualization, TabStrip
from .files import Files, FileTransfers
from .nudges import Nudges
from .observation import BrowserPerception, ImageContext
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
    *plugins: PluginLike | PluginPack | None,
    browser: Chrome | None = None,
    without: Iterable[type[Plugin]] = (),
) -> list[PluginLike]:
    """The default browser agent plugins, adjusted by `plugins` and `without`.

    A plugin that fills the same slot as a default
    replaces it in place, such as `BrowserPerception(...)`, `Readiness(...)` or
    `ContextCompaction(...)`; any other plugin is added. `without` drops defaults by type,
    such as `(Files, FileTools)` for an agent without local files. `None`
    entries are skipped, so optional plugins can be written inline.
    """
    pack = browser_pack(browser=browser).without(*without)
    # The flat API leaves prompt configuration to its caller.
    composition = PluginPack("browserrig.application", plugins=[pack, *plugins])
    return list(composition.resolve(prompt=PluginPackPromptPolicy.OMIT).plugins)


def browser_pack(*, browser: Chrome | None = None) -> PluginPack:
    """Browser defaults with Markdown instructions in configured plugin-list order.

    Pass a configured `Chrome` plugin, such as `Chrome.launch(url=...)` or
    `Chrome.connect(endpoint=...)`.
    Resources open only when the pack is mounted in a session.
    """
    if browser is not None and not isinstance(browser, Chrome):
        raise TypeError(
            "browser must be a Chrome plugin; use Chrome.launch(...) or Chrome.connect(...)"
        )
    return PluginPack(
        name="browserrig",
        plugins=[
            Activity(),
            browser if browser is not None else Chrome(),
            # Types and moves the pointer at a person's pace.
            InputPacing(),
            # Streams input and browser UI for anyone watching the session.
            InputVisualization(),
            # Titles and favicons for a viewer's tab strip; the agent reads tabs without it.
            TabStrip(),
            Readiness(),
            DownloadReadiness(),
            Nudges(),
            BrowserPerception(),
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
            # The agent's workspace, independent of the browser.
            Files(),
            FileTransfers(),
            DownloadReceiving(),
            FileTools(),
            ContextCompaction(trigger=WindowRatio()),
        ],
        prompt=SystemPrompt.from_plugins(
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
