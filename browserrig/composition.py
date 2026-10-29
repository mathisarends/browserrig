from harnessed import Plugin
from harnessed.plugins import LatestObservationOnly

from .activity import Activity
from .browser import Chrome
from .browser.config import BrowserOptions
from .nudges import Nudges
from .observation.config import DomMode, ObservationMode
from .observation.plugin import Observe
from .readiness.config import ReadinessOptions
from .readiness.plugin import Readiness
from .recording import Recording, RecordingOptions
from .tools import (
    DialogTools,
    FileTools,
    FormTools,
    InteractionTools,
    KeyboardTools,
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
    selected = mode or DomMode()
    plugins: list[Plugin] = [
        Activity(),
        Chrome(options),
        Readiness(selected, readiness),
        Nudges(),
        Observe(),
        Actions(),
        NavigationTools(),
        KeyboardTools(),
        InteractionTools() if isinstance(selected, DomMode) else PointerTools(),
        TabTools(),
        DialogTools(),
        LatestObservationOnly(),
    ]
    if isinstance(selected, DomMode):
        plugins.extend((FormTools(), FileTools()))
    if recording is not None:
        plugins.append(Recording(recording))
    return plugins
