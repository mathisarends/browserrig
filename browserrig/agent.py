"""Browser composition with Harnessed's native Agent and Session APIs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from harnessed import Agent
from harnessed.core.prompt.values import InstructionValues
from harnessed.kernel import PluginLike
from harnessed.models import Model
from harnessed.plugins import Approvals, JsonlSessions

from .browser.config import BrowserOptions
from .composition import browser_plugins
from .observation.config import ObservationMode
from .readiness.config import ReadinessOptions
from .recording import RecordingOptions

if TYPE_CHECKING:
    from pydantic_ai.models import Model as NativeModel


class BrowserAgent(Agent):
    """Configure browser capabilities; Harnessed owns execution and session lifetimes.

    Harnessed manages native model contexts; explicitly supplied provider clients remain
    caller-owned. Session storage is in memory unless session_directory is supplied;
    approvals retain Harnessed's defaults unless configured.
    Additional plugins use the same extension points and slot checks as a plain Agent.
    """

    def __init__(
        self,
        *,
        model: Model | str | NativeModel | None = None,
        browser: BrowserOptions | None = None,
        mode: ObservationMode | None = None,
        readiness: ReadinessOptions | None = None,
        recording: RecordingOptions | None = None,
        session_directory: str | Path | None = None,
        approvals: Approvals | None = None,
        instructions: InstructionValues | None = (
            "Complete the requested browser task using the observed page state."
        ),
        plugins: Iterable[PluginLike] = (),
    ) -> None:
        composed: list[PluginLike] = list(
            browser_plugins(browser, mode=mode, readiness=readiness, recording=recording)
        )
        if session_directory is not None:
            composed.append(JsonlSessions(session_directory))
        if approvals is not None:
            composed.append(approvals)
        composed.extend(plugins)
        super().__init__(model=model, instructions=instructions, plugins=composed)
