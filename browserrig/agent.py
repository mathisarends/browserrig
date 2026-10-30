from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from harnessed import Agent, PluginValidation, SystemPrompt
from harnessed.kernel import PluginLike
from harnessed.models import Model
from harnessed.plugins import Approvals, JsonlSessions

from browserrig.core.modes import ObservationMode

from .browser.config import BrowserOptions
from .composition import browser_plugins
from .files import FileSystemOptions
from .observation import Observe
from .observation.images import ImageContext
from .readiness import Readiness
from .readiness.config import ReadinessOptions
from .secrets import Secret, Secrets
from .tools.execution import Actions

if TYPE_CHECKING:
    from pydantic_ai.models import Model as NativeModel


class BrowserAgent(Agent):
    """Explicit provider clients remain caller-owned.

    Sessions stay in memory unless session_directory is supplied.
    Approvals use Harnessed's defaults unless configured.
    """

    def __init__(
        self,
        *,
        model: Model | str | NativeModel | None = None,
        browser: BrowserOptions | None = None,
        mode: ObservationMode | None = None,
        readiness: ReadinessOptions | Readiness | None = None,
        file_system: FileSystemOptions | None = None,
        observe: Observe | None = None,
        image_context: ImageContext | None = None,
        actions: Actions | None = None,
        local_files: bool = True,
        secrets: Secrets | Mapping[str, Secret] | None = None,
        session_directory: str | Path | None = None,
        approvals: Approvals | None = None,
        system_prompt: str | SystemPrompt | None = (
            "Complete the requested browser task using the observed page state."
        ),
        plugins: Iterable[PluginLike] = (),
        plugin_validation: PluginValidation = PluginValidation.ERROR,
    ) -> None:
        composed: list[PluginLike] = list(
            browser_plugins(
                browser,
                mode=mode,
                readiness=readiness,
                file_system=file_system,
                observe=observe,
                image_context=image_context,
                actions=actions,
                local_files=local_files,
                secrets=secrets,
            )
        )
        if session_directory is not None:
            composed.append(JsonlSessions(session_directory))
        if approvals is not None:
            composed.append(approvals)
        composed.extend(plugins)
        super().__init__(
            model=model,
            system_prompt=system_prompt,
            plugins=composed,
            plugin_validation=plugin_validation,
        )
