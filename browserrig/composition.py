from collections.abc import Mapping

from harnessed import Plugin

from .activity import Activity
from .browser import BrowserOptions, Chrome
from .choreography import Choreography, TabStrip
from .handoff import HumanHandoff
from .nudges import Nudges
from .observation import ImageContext, Observe
from .readiness import DownloadReadiness, Readiness, ReadinessOptions
from .secrets import Secret, Secrets
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
    options: BrowserOptions | None = None,
    *,
    readiness: ReadinessOptions | Readiness | None = None,
    observe: Observe | None = None,
    image_context: ImageContext | None = None,
    actions: Actions | None = None,
    local_files: bool = True,
    secrets: Secrets | Mapping[str, Secret] | None = None,
    handoff: HumanHandoff | None = None,
    choreography: bool = True,
    tab_strip: bool = True,
) -> list[Plugin]:
    observation = observe or Observe()
    plugins: list[Plugin] = [
        Activity(),
        Chrome(options),
    ]
    if choreography:
        # Paces input like a person and streams it, for anyone watching the session.
        plugins.append(Choreography())
    if tab_strip:
        # Titles and favicons for a viewer's tab strip; the agent reads tabs without it.
        plugins.append(TabStrip())
    plugins += [
        readiness if isinstance(readiness, Readiness) else Readiness(options=readiness),
        DownloadReadiness(),
        Nudges(),
    ]
    if secrets is not None:
        plugins.append(secrets if isinstance(secrets, Secrets) else Secrets(secrets))
    plugins += [
        observation,
        image_context or ImageContext(),
        actions or Actions(),
        NavigationTools(),
        JavaScriptTools(),
        KeyboardTools(),
        PointerTools(),
        FormTools(),
        TabTools(),
        DialogTools(),
        FindTools(),
    ]
    if local_files:
        plugins += [FileTools(), UploadTools()]
    if handoff is not None:
        plugins.append(handoff)
    return plugins
