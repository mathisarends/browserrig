from collections.abc import Iterable
from dataclasses import dataclass

from harnessed import Kit, Plugin, SystemPrompt
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
    return list(compose_plugins([kit, *(p for p in plugins if p is not None)]).plugins)


def browser_kit(*, browser: BrowserOptions | None = None) -> Kit:
    """Browser defaults as a native Harnessed kit, with explicit instruction ordering.

    Its `observation`, `actions` and `files` fragments group the instructions in
    reading order; `browser_instructions` places them in that order.
    """
    observe, images = Observe(), ImageContext()
    actions, pointer = Actions(), PointerTools()
    files = FileTools()
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
            observe,
            images,
            actions,
            NavigationTools(),
            JavaScriptTools(),
            KeyboardTools(),
            pointer,
            FormTools(),
            TabTools(),
            DialogTools(),
            FindTools(),
            files,
            ContextCompaction(trigger=WindowRatio()),
        ],
        # Instruction order differs from mount order: coordinates are explained right
        # after screenshots and before the chain rules that refer to them.
        fragments={
            "observation": (observe, images),
            "actions": (pointer, actions),
            "files": (files,),
        },
    )


def browser_instructions(kit: Kit) -> SystemPrompt:
    """`browser_kit` instructions in reading order: what the agent sees, how it acts, files.

    Removed and replaced recipes follow the kit, like `kit.instructions`. Kit plugins
    outside these fragments declare no instructions; place them with `PluginInstructions()`.
    """
    return SystemPrompt(
        kit.fragment("observation"), kit.fragment("actions"), kit.fragment("files")
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
