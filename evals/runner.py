"""Run a frozen WebArena task and grade its recorded evidence with upstream rules."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from harnessed import PolicyDecision, ToolCall, ToolStatus
from harnessed.events import ToolCallFinishedEvent
from harnessed.kernel import PluginLike
from harnessed.models import Message
from harnessed.plugins import Approvals
from pydantic import ConfigDict, TypeAdapter
from pydantic_core import PydanticSerializationError

from browserrig import (
    Agent,
    Chrome,
    Files,
    InputPacing,
    InputVisualization,
    LocalWorkspace,
)

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
class RunOptions:
    model: str | NativeModel
    headed: bool = False
    humanlike: bool = False
    plugins: tuple[PluginLike, ...] = ()
    max_steps: int = 50
    timeout: int = 300

    def __post_init__(self) -> None:
        if self.max_steps < 1 or self.timeout < 1:
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
            async with _agent(
                options, workspace / "agent", endpoint, target
            ).session() as session:
                record.session_id = session.id
                phase = "execution"
                try:
                    async with asyncio.timeout(options.timeout):
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


def _agent(options: RunOptions, workspace: Path, endpoint: str, target: str) -> Agent:
    # Provider dependencies are only needed for actual model execution.
    # pylint: disable=import-outside-toplevel
    from harnessed.models.pydantic_ai import PydanticAIModel

    return Agent(
        model=PydanticAIModel(options.model),
        browser=Chrome.connect(endpoint=endpoint, target_id=target),
        plugins=[
            Files(LocalWorkspace(workspace)),
            Approvals(default=PolicyDecision.ALLOW),
            *options.plugins,
        ],
        without=() if options.humanlike else (InputPacing, InputVisualization),
    )


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
