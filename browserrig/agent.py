from collections.abc import Iterable

import harnessed
from harnessed import (
    Plugin,
    PluginPack,
    PluginValidation,
    PromptFormat,
    SystemPrompt,
)
from harnessed.kernel import PluginLike
from harnessed.models import Model
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Service
from harnessed.runtime.budget import ContextBudget
from harnessed.sessions import SessionStore

from .activity import Activity
from .browser import Chrome, DownloadReceiving, MultiTab
from .choreography import Choreography, TabStrip
from .composition import WindowRatio
from .core import MODEL_PROFILES, ModelProfile, Runtime
from .dom import DomPage
from .files import Files, FileTransfers
from .input import InputRuntime
from .memory import TaskMemory
from .nudges import Nudges
from .observation import BrowserPerception, Screenshots, SetOfMarks
from .overlay import ChoreographyOverlay
from .pacing import InputPacing
from .readiness import DownloadReadiness, PageReadiness
from .tools import (
    Actions,
    DialogTools,
    DomActionChains,
    DomScrollTools,
    DomTypingTools,
    FileTools,
    FormTools,
    JavaScriptTools,
    KeyboardTools,
    NavigationTools,
    PageSearchTools,
    PointerTools,
    ReferencePointerTools,
    ScreenshotTools,
    TabTools,
    Targeting,
)

DEFAULT_PROMPT = "Complete the requested browser task using the observed page state."


class Agent(harnessed.Agent):
    """A harnessed agent with browserrig's default browser plugins.

    `plugins` replace the defaults they match and add the rest, and `without`
    drops defaults by type. Explicit provider clients remain caller-owned.
    Pass `browser=Chrome.launch(...)` to start Chrome or
    `browser=Chrome.connect(...)` to use an existing browser when the session opens.
    Conversations stay in memory by default; pass `store`
    to reopen them by ID, or continue with an explicit `SessionState`. Long runs
    summarize older steps once the request fills 80% of the model's context window,
    with a 256k application limit for GPT-6.1 Terra, or 100k tokens for other models
    when no window is known. Pass `without=(ContextCompaction,)`
    to keep everything, or a configured `ContextCompaction`. Input is paced like a
    person and streamed and drawn for people watching; pass
    `without=(InputPacing, Choreography, ChoreographyOverlay)` to work at full speed
    unseen.

    The default `TaskMemory` compaction asks for a workspace checkpoint before
    summarizing and an explicit read afterward. Configure `TaskMemory(...)` to
    tune this protocol; plain `ContextCompaction(...)` disables its memory guidance.
    """

    def __init__(
        self,
        *,
        model: Model | str | None = None,
        browser: Chrome | None = None,
        plugins: Iterable[PluginLike | PluginPack | None] = (),
        without: Iterable[type[Plugin]] = (),
        instructions: str | None = DEFAULT_PROMPT,
        prompt: SystemPrompt | None = None,
        store: SessionStore | None = None,
        plugin_validation: PluginValidation = PluginValidation.ERROR,
    ) -> None:
        profile = MODEL_PROFILES.get(_model_name(model))
        if isinstance(model, str) and profile is not None:
            model = PydanticAIModel(model, context_window=profile.context_window)
        defaults: list[PluginLike] = []
        if profile is not None:
            defaults.append(
                Service(
                    ContextBudget,
                    ContextBudget(
                        limit=profile.context_window,
                        reserve_tokens=profile.reserve_tokens,
                    ),
                )
            )
        # Use Harnessed's resolver for default replacements and exclusions.
        recipe = PluginPack(
            "browserrig",
            plugins=_browser_defaults(browser, profile),
            prompt=SystemPrompt.from_plugins(format=PromptFormat.MARKDOWN),
        ).without(*without)
        super().__init__(
            model=model,
            instructions=instructions,
            prompt=prompt,
            plugins=[recipe, *defaults, *plugins],
            store=store,
            plugin_validation=plugin_validation,
        )


def _model_name(model: Model | str | None) -> str:
    if isinstance(model, str):
        return model.rsplit(":", 1)[-1]
    if isinstance(model, Model):
        return model.info.name
    return ""


def _browser_defaults(
    browser: Chrome | None, model_profile: ModelProfile | None
) -> list[PluginLike]:
    if browser is not None and not isinstance(browser, Chrome):
        raise TypeError(
            "browser must be a Chrome plugin; use Chrome.launch(...) or Chrome.connect(...)"
        )
    return [
        Runtime(),
        Activity(),
        browser if browser is not None else Chrome(),
        InputRuntime(),
        Targeting(),
        # Types and moves the pointer at a person's pace.
        InputPacing(),
        # Streams input and browser UI for anyone watching the session.
        Choreography(),
        # Draws that stream inside the active tab, for live viewers and recordings.
        ChoreographyOverlay(),
        # Titles and favicons for a viewer's tab strip; the agent reads tabs without it.
        TabStrip(),
        PageReadiness(),
        DownloadReadiness(),
        Nudges(),
        BrowserPerception(),
        Screenshots(),
        # Reads pages into controls with refs and prose; screenshots label those refs.
        DomPage(),
        SetOfMarks(),
        # Explain screenshot coordinates before the chains that refer to them.
        # Harnessed resolves setup dependencies independently of prompt order.
        PointerTools(),
        ReferencePointerTools(),
        Actions(chain_policy=DomActionChains()),
        MultiTab(),
        NavigationTools(),
        JavaScriptTools(),
        KeyboardTools(),
        DomTypingTools(),
        DomScrollTools(),
        ScreenshotTools(),
        FormTools(),
        TabTools(),
        DialogTools(),
        PageSearchTools(),
        # The agent's workspace, independent of the browser.
        Files(),
        FileTransfers(),
        DownloadReceiving(),
        FileTools(),
        TaskMemory(
            trigger=WindowRatio(),
            keep_last_steps=model_profile.keep_last_steps if model_profile else 2,
            target_ratio=model_profile.target_ratio if model_profile else None,
            max_summary_tokens=(
                model_profile.max_summary_tokens if model_profile else None
            ),
        ),
    ]
