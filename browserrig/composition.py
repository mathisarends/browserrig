from harnessed import Plugin
from harnessed.plugins import LatestObservationOnly

from .activity import Activity
from .browser import Chrome
from .browser.config import BrowserOptions
from .nudges import Nudges
from .observation.config import ObservationMode, WebMode
from .observation.plugin import Observe
from .readiness.config import ReadinessOptions
from .readiness.plugin import Readiness
from .recording import Recording, RecordingOptions
from .tools import (
    DialogTools,
    FileTools,
    FormTools,
    InteractionTools,
    NavigationTools,
    PointerTools,
    TabTools,
)
from .tools.execution import Actions


def browser_plugins(
    options: BrowserOptions | None = None,
    *,
    mode: ObservationMode | None = None,
    readiness: ReadinessOptions | None = None,
    recording: RecordingOptions | None = None,
) -> list[Plugin]:
    """An ordinary, inspectable plugin list. Policies and provider remain caller choices."""
    selected = mode or WebMode()
    plugins: list[Plugin] = [
        Activity(),
        Chrome(options),
        Readiness(selected, readiness),
        Nudges(),
        Observe(),
        Actions(),
        NavigationTools(),
        InteractionTools() if isinstance(selected, WebMode) else PointerTools(),
        TabTools(),
        DialogTools(),
        LatestObservationOnly(),
    ]
    if isinstance(selected, WebMode):
        plugins.extend((FormTools(), FileTools()))
    if recording is not None:
        plugins.append(Recording(recording))
    return plugins
