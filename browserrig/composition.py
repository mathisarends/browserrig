from harnessed import Plugin
from harnessed.plugins import LatestObservationOnly

from browserrig.core.modes import DomMode, ObservationMode

from .activity import Activity
from .browser import Chrome
from .browser.config import BrowserOptions
from .files import FileSystemOptions
from .nudges import Nudges
from .observation.plugin import Observe
from .readiness.config import ReadinessOptions
from .readiness.plugin import Readiness
from .recording import Recording, RecordingOptions
from .tools import (
    DialogTools,
    FileTools,
    FormTools,
    KeyboardTools,
    MouseTools,
    NavigationTools,
    TabTools,
    UploadTools,
)
from .tools.execution import Actions


def browser_plugins(
    options: BrowserOptions | None = None,
    *,
    mode: ObservationMode | None = None,
    readiness: ReadinessOptions | None = None,
    recording: RecordingOptions | None = None,
    file_system: FileSystemOptions | None = None,
) -> list[Plugin]:
    selected = mode or DomMode()
    plugins: list[Plugin] = [
        Activity(),
        Chrome(options, file_system=file_system),
        Readiness(selected, readiness),
        Nudges(),
        Observe(selected),
        Actions(),
        NavigationTools(),
        KeyboardTools(),
        MouseTools(),
        TabTools(),
        DialogTools(),
        FileTools(),
        LatestObservationOnly(),
    ]
    if isinstance(selected, DomMode):
        plugins.extend((FormTools(), UploadTools()))
    if recording is not None:
        plugins.append(Recording(recording))
    return plugins
