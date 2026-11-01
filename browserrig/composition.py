from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from harnessed import Plugin
from harnessed.errors import PluginConflict
from harnessed.kernel import PluginLike
from harnessed.kernel.plugin import as_plugin_spec
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
    UploadTools,
)


def browser_plugins(
    *plugins: PluginLike | None,
    browser: BrowserOptions | None = None,
    without: Iterable[type[Plugin]] = (),
) -> list[PluginLike]:
    """The default browser agent plugins, adjusted by `plugins` and `without`.

    A plugin that provides the same service or fills the same slot as a default
    replaces it in place, such as `Observe(...)`, `Readiness(...)` or
    `Compaction(...)`; any other plugin is added. `without` drops defaults by type,
    such as `(FileTools, UploadTools)` for an agent without local files. `None`
    entries are skipped, so optional plugins can be written inline.
    """
    defaults: list[PluginLike] = [
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
        UploadTools(),
        Compaction(trigger=WindowRatio()),
    ]
    return _compose(defaults, plugins, without=tuple(without))


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


def _compose(
    defaults: list[PluginLike],
    plugins: Sequence[PluginLike | None],
    *,
    without: tuple[type[Plugin], ...],
) -> list[PluginLike]:
    unknown = [
        kind.__name__
        for kind in without
        if not any(isinstance(plugin, kind) for plugin in defaults)
    ]
    if unknown:
        raise ValueError(f"Not a browserrig default: {', '.join(unknown)}")
    composed = [plugin for plugin in defaults if not isinstance(plugin, without)]
    positions = {
        key: index
        for index, plugin in enumerate(composed)
        if (key := _identity(plugin)) is not None
    }
    chosen: set[str | frozenset[object]] = set()
    for plugin in plugins:
        if plugin is None:
            continue
        key = _identity(plugin)
        if key is None:
            composed.append(plugin)
            continue
        if key in chosen:
            raise PluginConflict(f"Two plugins for {_describe(key)}")
        chosen.add(key)
        if key in positions:
            composed[positions[key]] = plugin
        else:
            composed.append(plugin)
    return composed


def _identity(plugin: PluginLike) -> str | frozenset[object] | None:
    """The slot a plugin fills, or else the services it provides."""
    spec = as_plugin_spec(plugin)
    return spec.slot or frozenset(spec.provides) or None


def _describe(key: str | frozenset[object]) -> str:
    if isinstance(key, str):
        return f"slot {key!r}"
    return ", ".join(sorted(getattr(item, "__name__", repr(item)) for item in key))
