"""Run a frozen WebArena task and grade its recorded evidence with upstream rules."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from harnessed import Agent, Compaction, Context, Plugin, SystemPrompt
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import Message, Model, ToolCall, ToolStatus
from harnessed.prompts import PromptFormat
from pydantic import ConfigDict, TypeAdapter
from pydantic_core import PydanticSerializationError

from browserrig import (
    Actions,
    Activity,
    BrowserPerception,
    Choreography,
    ChoreographyOverlay,
    Chrome,
    DialogTools,
    DomActionChains,
    DomPage,
    DomScrollTools,
    DomTypingTools,
    DownloadReadiness,
    DownloadReceiving,
    Files,
    FileTools,
    FileTransfers,
    FormTools,
    InputPacing,
    InputRuntime,
    JavaScriptTools,
    KeyboardTools,
    LocalWorkspace,
    MultiTab,
    NavigationTools,
    NetworkQuiet,
    Nudges,
    PageReadiness,
    PageSearchTools,
    PointerTools,
    ReferencePointerTools,
    Runtime,
    Screenshots,
    ScreenshotTools,
    ScreenshotTrigger,
    SetOfMarks,
    TabStrip,
    TabTools,
    Targeting,
    TaskMemory,
    WheelTools,
    WorkspaceTools,
)
from browserrig.core import MODEL_PROFILES
from browserrig.dom import PageProse
from browserrig.readiness import BrowserReady

from .environments import Environments
from .evaluate import evaluate
from .recording import recording_browser
from .results import AgentResponse, TaskResult, ToolRecord, Usage
from .task import Task

if TYPE_CHECKING:
    from pydantic_ai.models import Model as NativeModel

_TOOL_CALL_ADAPTER = TypeAdapter(ToolCall)
_MESSAGES_ADAPTER = TypeAdapter(
    list[Message], config=ConfigDict(ser_json_bytes="base64")
)


@dataclass(frozen=True)
class ObservationOptions:
    mode: str | None = None
    trigger: ScreenshotTrigger | None = ScreenshotTrigger.ON_REQUEST
    screenshot_tool: bool = True
    prose: PageProse = "inline"
    headings: bool = True
    landmarks: bool = True

    @property
    def text(self) -> bool:
        return self.mode is None or self.mode.startswith("text")


@dataclass(frozen=True)
class RunOptions:
    model: str | NativeModel
    headed: bool = False
    humanlike: bool = False
    plugins: tuple[Plugin, ...] = ()
    max_steps: int = 50
    timeout_seconds: int = 300
    observation: ObservationOptions = ObservationOptions()

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.timeout_seconds < 1:
            raise ValueError("Step and time budgets must be at least 1")


async def run_task(
    task: Task,
    options: RunOptions,
    workspace: Path,
    attempt: int = 1,
    environments: Environments | None = None,
) -> TaskResult:
    """Isolate failures per attempt; cancellation propagates after flushing the HAR."""
    environments = environments or Environments()
    environments = environments.for_task(task.sites)
    record = TaskResult(
        task=task.name,
        task_id=task.task_id,
        revision=task.revision,
        stage="webarena-verified-hard",
        tags=[*task.sites, task.action],
        sites=list(task.sites),
        attempt=attempt,
        url=environments.render(task.start_urls[0]),
        workspace=str(workspace),
        status="error",
        score=0,
        seconds=0,
    )
    phase: Literal["setup", "execution", "evidence", "checks", "evaluation"] = "setup"
    started = time.monotonic()
    try:
        workspace.mkdir(parents=True, exist_ok=False)
        (workspace / "agent").mkdir()
        (workspace / "environment.json").write_text(
            json.dumps(environments.evaluator_config(), indent=2), encoding="utf-8"
        )
        await environments.reset(task.sites, workspace / "environment.log")
        async with recording_browser(
            task, environments, workspace, headless=not options.headed
        ) as (endpoint, target):
            async with build_agent(
                options, workspace / "agent", endpoint, target
            ).session() as session:
                record.session_id = session.id
                phase = "execution"
                try:
                    async with asyncio.timeout(options.timeout_seconds):
                        result = await session.run(
                            task_prompt(task, environments),
                            output=AgentResponse,
                            max_steps=options.max_steps,
                        )
                except TimeoutError:
                    record.completed = False
                    record.stop_reason = "timeout"
                else:
                    phase = "evidence"
                    _capture(record, result)
                    _write_messages(result.messages, workspace)
            # Grading files are outside the agent's Files workspace.
            (workspace / "agent_response.json").write_text(
                record.answer or "null", encoding="utf-8"
            )
        phase = "evaluation"
        grade = await evaluate(workspace)
        record.checks = grade.checks()
        record.score = grade.score if record.completed else 0
        record.status = (
            "pass" if record.completed and grade.status == "success" else "fail"
        )
        if grade.status == "error" and record.completed:
            record.status = "error"
            record.error = (
                grade.error_msg
                or "; ".join(check.error for check in record.checks if check.error)
                or "Upstream evaluator error; see eval_result.json"
            )
            record.error_phase = phase
    except Exception as error:  # pylint: disable=broad-exception-caught
        record.status = "error"
        record.error = f"{type(error).__name__}: {error}"
        record.error_phase = phase
    finally:
        record.seconds = round(time.monotonic() - started, 1)
    return record


def task_prompt(task: Task, environments: Environments) -> str:
    """Expose the original intent and output contract, never reference answers."""
    sites = "\n".join(
        f"- {name}: {environments.sites[name].url}" for name in task.sites
    )
    return (
        f"{environments.render(task.intent)}\n\n"
        f"Available websites (already signed in):\n{sites}\n\n"
        "Complete the task through the browser. Do not inspect local benchmark files, "
        "use direct HTTP clients, execute page JavaScript, or access environment control APIs. "
        "Use only these benchmark websites and links between them.\n"
        "Return the WebArena structured response: task_type RETRIEVE, MUTATE or NAVIGATE; "
        "status SUCCESS or the appropriate error status; retrieved_data and error_details. "
        "For RETRIEVE use the following result schema; for NAVIGATE finish on the requested "
        "page; for MUTATE and NAVIGATE leave retrieved_data null. Report failures honestly.\n"
        f"Result schema: {json.dumps(task.response_schema, ensure_ascii=False)}"
    )


def build_agent(
    options: RunOptions, workspace: Path, endpoint: str, target: str
) -> Agent:
    """Build the agent for an eval attempt using the selected benchmark settings."""
    # Provider dependencies are only needed for actual model execution.
    # pylint: disable=import-outside-toplevel
    from harnessed.models.pydantic_ai import PydanticAIModel

    model = PydanticAIModel(options.model)
    return Agent(
        model=model,
        instructions=SystemPrompt.from_plugins(
            "Complete the requested browser task using the observed page state.",
            format=PromptFormat.MARKDOWN,
        ),
        context=_context(model),
        plugins=_agent_plugins(
            options, Chrome.connect(endpoint=endpoint, target_id=target), workspace
        ),
    )


def _context(model: Model) -> Context:
    profile = MODEL_PROFILES.get(model.info.name)
    return Context(
        max_tokens=profile.context_window if profile else None,
        reserve_tokens=profile.reserve_tokens if profile else 0,
        compaction=Compaction(
            at=0.8,
            fallback_tokens=100_000,
            keep_last_steps=profile.keep_last_steps if profile else 2,
            target_ratio=profile.target_ratio if profile else None,
            max_summary_tokens=profile.max_summary_tokens if profile else None,
        ),
    )


def _agent_plugins(
    options: RunOptions, browser: Chrome, workspace: Path
) -> list[Plugin]:
    observation = options.observation
    presentation = (
        [InputPacing(), Choreography(), ChoreographyOverlay()]
        if options.humanlike
        else []
    )
    return [
        Runtime(),
        Activity(),
        browser,
        InputRuntime(),
        Targeting(),
        *presentation,
        TabStrip(),
        _page_readiness(observation),
        DownloadReadiness(),
        *([Nudges()] if observation.text else []),
        *_perception_plugins(observation),
        *_browser_tools(observation),
        Files(LocalWorkspace(workspace)),
        FileTransfers(),
        DownloadReceiving(),
        FileTools() if observation.text else WorkspaceTools(),
        TaskMemory(),
        *options.plugins,
        *([] if observation.text else [WheelTools()]),
    ]


def _page_readiness(observation: ObservationOptions) -> PageReadiness:
    if observation.mode == "screenshot":
        policy = NetworkQuiet(inner=BrowserReady())
        return PageReadiness(initial=policy, ongoing=policy)
    return PageReadiness()


def _perception_plugins(observation: ObservationOptions) -> list[Plugin]:
    text = None
    if observation.text:
        text = "delta" if observation.mode is None else "full"
    # Preserve the effective DOM defaults and marks used in previous eval runs.
    if observation.mode == "screenshot":
        dom = DomPage()
    else:
        dom = DomPage(
            prose=observation.prose,
            headings=observation.headings,
            landmarks=observation.landmarks,
        )
    return [
        BrowserPerception(text=text),
        Screenshots(
            trigger=observation.trigger or ScreenshotTrigger.ON_REQUEST,
            skip_unchanged=observation.mode in (None, "text"),
        ),
        dom,
        SetOfMarks(),
    ]


def _browser_tools(observation: ObservationOptions) -> list[Plugin]:
    text = observation.text
    return [
        PointerTools(),
        ReferencePointerTools(),
        Actions(chain_policy=DomActionChains()) if text else Actions(),
        MultiTab(),
        NavigationTools(),
        *([JavaScriptTools()] if text else []),
        KeyboardTools(),
        *([DomTypingTools(), DomScrollTools()] if text else []),
        *([ScreenshotTools()] if observation.screenshot_tool else []),
        *([FormTools()] if text else []),
        TabTools(),
        DialogTools(),
        *([PageSearchTools()] if text else []),
    ]


def _write_messages(messages: Iterable[Message], workspace: Path) -> None:
    values = list(messages)
    try:
        payload = _MESSAGES_ADAPTER.dump_json(values)
    except PydanticSerializationError:
        payload = json.dumps([repr(message) for message in values]).encode("utf-8")
    (workspace / "messages.json").write_bytes(payload)


def _capture(record: TaskResult, result) -> None:
    record.completed = result.completed
    record.stop_reason = str(result.stop_reason)
    # Harnessed raises when output is accessed on an unfinished turn.
    if result.completed:
        record.answer = AgentResponse.model_validate(result.output).model_dump_json(
            indent=2
        )
    record.usage = Usage(
        input=result.usage.input_tokens,
        output=result.usage.output_tokens,
        cache_read=result.usage.cache_read_tokens,
        reasoning=result.usage.reasoning_tokens,
    )
    record.tools = _tool_calls(result.events)
    record.tool_calls = len(record.tools)
    record.tool_errors = sum(tool.error for tool in record.tools)
    record.tool_skipped = sum(tool.skipped for tool in record.tools)


def _tool_calls(events: Iterable[object]) -> list[ToolRecord]:
    calls: list[ToolRecord] = []
    for event in events:
        if not isinstance(event, ToolCallFinishedEvent):
            continue
        content = event.result.content
        skipped = event.result.status is ToolStatus.SKIPPED
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        call = _TOOL_CALL_ADAPTER.dump_python(event.call, mode="json")
        calls.append(
            ToolRecord(
                name=event.call.name,
                args=call["arguments"],
                error=event.result.is_error and not skipped,
                skipped=skipped,
                chars=len(text),
                preview=text[:300],
            )
        )
    return calls
