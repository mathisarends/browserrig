from collections.abc import Iterable

import harnessed
from harnessed import (
    AgentLoop,
    Approvals,
    Compaction,
    Context,
    Plugin,
    PluginValidation,
    SystemPrompt,
)
from harnessed.models import Model
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.prompts import PromptFormat
from harnessed.sessions import SessionStore

from .activity import Activity
from .browser import Chrome, DownloadReceiving, MultiTab
from .choreography import Choreography, TabStrip
from .composition import select_plugins
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
    when no window is known. Pass `context=Context(...)` to supply your own budgets
    and compaction settings. Input is paced for live viewing. Pass
    `without=(InputPacing, Choreography, ChoreographyOverlay)` to work at full speed
    unseen.

    The default `TaskMemory` plugin asks for a workspace checkpoint before
    summarizing and an explicit read afterward. With an explicit context, add
    `TaskMemory()` to enable its guidance alongside your compaction settings.
    """

    def __init__(
        self,
        *,
        model: Model | str | None = None,
        browser: Chrome | None = None,
        plugins: Iterable[Plugin] = (),
        without: Iterable[type[Plugin]] = (),
        instructions: str | SystemPrompt | None = DEFAULT_PROMPT,
        approvals: Approvals | None = None,
        context: Context | None = None,
        loop: AgentLoop | None = None,
        store: SessionStore | None = None,
        plugin_validation: PluginValidation = PluginValidation.ERROR,
    ) -> None:
        profile = MODEL_PROFILES.get(_model_name(model))
        if isinstance(model, str) and profile is not None:
            model = PydanticAIModel(model, context_window=profile.context_window)
        selected = _select_browser_plugins(browser, plugins, without, context=context)
        super().__init__(
            model=model,
            instructions=_instructions(instructions),
            approvals=approvals,
            context=_context_settings(context, profile, selected),
            loop=loop,
            plugins=selected,
            store=store,
            plugin_validation=plugin_validation,
        )


def _model_name(model: Model | str | None) -> str:
    if isinstance(model, str):
        return model.rsplit(":", 1)[-1]
    if isinstance(model, Model):
        return model.info.name
    return ""


def _select_browser_plugins(
    browser: Chrome | None,
    plugins: Iterable[Plugin],
    without: Iterable[type[Plugin]],
    *,
    context: Context | None,
) -> list[Plugin]:
    task_memory = TaskMemory()
    selected = select_plugins(
        [*_browser_defaults(browser), task_memory], plugins, without
    )
    if context is not None:
        selected = [plugin for plugin in selected if plugin is not task_memory]
    return selected


def _instructions(value: str | SystemPrompt | None) -> SystemPrompt:
    if isinstance(value, SystemPrompt):
        return value
    return SystemPrompt.from_plugins(value, format=PromptFormat.MARKDOWN)


def _context_settings(
    context: Context | None, profile: ModelProfile | None, plugins: list[Plugin]
) -> Context:
    if context is not None:
        return context
    compaction = None
    if any(isinstance(plugin, TaskMemory) for plugin in plugins):
        compaction = Compaction(
            at=0.8,
            fallback_tokens=100_000,
            keep_last_steps=profile.keep_last_steps if profile else 2,
            target_ratio=profile.target_ratio if profile else None,
            max_summary_tokens=profile.max_summary_tokens if profile else None,
        )
    return Context(
        max_tokens=profile.context_window if profile else None,
        reserve_tokens=profile.reserve_tokens if profile else 0,
        compaction=compaction,
    )


def _browser_defaults(browser: Chrome | None) -> list[Plugin]:
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
    ]
