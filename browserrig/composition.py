from collections.abc import Mapping

from harnessed import Plugin

from .activity import Activity
from .browser import Chrome
from .browser.config import BrowserOptions
from .files import FileSystemOptions
from .handoff import HumanHandoff
from .nudges import Nudges
from .observation import ImageContext, Observe
from .readiness import DownloadReadiness, Readiness, ReadinessOptions
from .secrets import Secret, Secrets
from .tools import (
    Actions,
    DialogTools,
    DomTools,
    FileTools,
    FindTools,
    JavaScriptTools,
    KeyboardTools,
    NavigationTools,
    PointerTools,
    TabTools,
    UploadTools,
)


def browser_plugins(
    options: BrowserOptions | None = None,
    *,
    readiness: ReadinessOptions | Readiness | None = None,
    file_system: FileSystemOptions | None = None,
    observe: Observe | None = None,
    image_context: ImageContext | None = None,
    actions: Actions | None = None,
    local_files: bool = True,
    secrets: Secrets | Mapping[str, Secret] | None = None,
    handoff: HumanHandoff | None = None,
) -> list[Plugin]:
    observation = observe or Observe()
    plugins: list[Plugin] = [
        Activity(),
        Chrome(options, file_system=file_system),
        readiness if isinstance(readiness, Readiness) else Readiness(options=readiness),
        DownloadReadiness(),
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
        FindTools(),
    ]
    if observation.capture_strategy.provides_dom_refs:
        plugins.append(DomTools())
    if local_files:
        plugins.append(FileTools())
        if observation.capture_strategy.provides_dom_refs:
            plugins.append(UploadTools())
    if handoff is not None:
        plugins.append(handoff)
    return plugins
