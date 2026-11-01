from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from harnessed import Agent, PluginValidation, SystemPrompt
from harnessed.kernel import PluginLike
from harnessed.models import Model
from harnessed.plugins import Approvals, Compaction, ContextState

from .browser import BrowserOptions
from .composition import browser_plugins
from .handoff import HumanHandoff
from .observation import ImageContext, Observe
from .readiness import Readiness, ReadinessOptions
from .secrets import Secret, Secrets
from .tools import Actions


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


DEFAULT_COMPACTION = Compaction(trigger=WindowRatio())


class BrowserAgent(Agent):
    """Explicit provider clients remain caller-owned.

    Conversations stay in memory; continue one by passing a saved `SessionState`
    to `run` or `session`. Long runs summarize older steps once the request fills
    80% of the model's context window, or 100k tokens when the model reports none;
    pass `compaction=None` to keep everything, or a configured `Compaction`.
    Approvals use Harnessed's defaults unless configured. Input is paced and streamed
    for people watching; pass `choreography=False` to work at full speed instead, and
    `tab_strip=False` to skip reading titles and favicons for a viewer's tab strip.
    """

    def __init__(
        self,
        *,
        model: Model | str | None = None,
        browser: BrowserOptions | None = None,
        readiness: ReadinessOptions | Readiness | None = None,
        observe: Observe | None = None,
        image_context: ImageContext | None = None,
        actions: Actions | None = None,
        local_files: bool = True,
        secrets: Secrets | Mapping[str, Secret] | None = None,
        handoff: HumanHandoff | None = None,
        choreography: bool = True,
        tab_strip: bool = True,
        compaction: Compaction | None = DEFAULT_COMPACTION,
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
                readiness=readiness,
                observe=observe,
                image_context=image_context,
                actions=actions,
                local_files=local_files,
                secrets=secrets,
                handoff=handoff,
                choreography=choreography,
                tab_strip=tab_strip,
            )
        )
        if compaction is not None:
            composed.append(compaction)
        if approvals is not None:
            composed.append(approvals)
        composed.extend(plugins)
        super().__init__(
            model=model,
            system_prompt=system_prompt,
            plugins=composed,
            plugin_validation=plugin_validation,
        )
