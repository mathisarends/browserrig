from collections.abc import Mapping

from harnessed import Plugin
from harnessed.plugins import LatestObservationOnly

from browserrig.core.modes import DomMode, ObservationMode

from .activity import Activity
from .browser import Chrome
from .browser.config import BrowserOptions
from .files import FileSystemOptions
from .nudges import Nudges
from .observation.images import ImageContext
from .observation.plugin import Observe
from .readiness.config import ReadinessOptions
from .readiness.plugin import Readiness
from .secrets import Secret, Secrets
from .tools import (
    DialogTools,
    DomTools,
    FileTools,
    JavaScriptTools,
    KeyboardTools,
    NavigationTools,
    PointerTools,
    TabTools,
    UploadTools,
)
from .tools.execution import Actions


def browser_plugins(
    options: BrowserOptions | None = None,
    *,
    mode: ObservationMode | None = None,
    readiness: ReadinessOptions | Readiness | None = None,
    file_system: FileSystemOptions | None = None,
    observe: Observe | None = None,
    image_context: ImageContext | None = None,
    actions: Actions | None = None,
    local_files: bool = True,
    secrets: Secrets | Mapping[str, Secret] | None = None,
) -> list[Plugin]:
    if mode is not None and observe is not None:
        raise ValueError("Choose mode or observe, not both")
    selected = mode or DomMode()
    observation = observe or Observe(selected)
    plugins: list[Plugin] = [
        Activity(),
        Chrome(options, file_system=file_system),
        readiness if isinstance(readiness, Readiness) else Readiness(selected, readiness),
        Nudges(),
    ]
    if secrets is not None:
        # Before Observe, which redacts every observation with it.
        plugins.append(secrets if isinstance(secrets, Secrets) else Secrets(secrets))
    plugins += [
        observation,
        image_context or ImageContext(),
        actions or Actions(),
        NavigationTools(),
        JavaScriptTools(),
        KeyboardTools(),
        PointerTools(),
        TabTools(),
        DialogTools(),
        LatestObservationOnly(),
    ]
    if observation.capture_strategy.provides_dom_refs:
        plugins.append(DomTools())
    if local_files:
        plugins.append(FileTools())
        if observation.capture_strategy.provides_dom_refs:
            plugins.append(UploadTools())
    return plugins
