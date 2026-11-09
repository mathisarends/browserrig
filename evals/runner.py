"""Run one task in its own browser and workspace and score its milestones."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from harnessed import PolicyDecision, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.kernel import PluginLike
from harnessed.plugins import Approvals
from pydantic import TypeAdapter

from browserrig import (
    Agent,
    Chrome,
    Files,
    InputPacing,
    InputVisualization,
    LocalWorkspace,
    Secrets,
)
from browserrig.browser import Browser

from .checks import Evidence
from .results import CheckResult, TaskResult, ToolRecord, Usage
from .task import Task

if TYPE_CHECKING:
    from pydantic_ai.models import Model as NativeModel

_TOOL_CALL_ADAPTER = TypeAdapter(ToolCall)


@dataclass(frozen=True)
class RunOptions:
    model: str | NativeModel
    headed: bool = False
    # Keep human-like input pacing and the on-page cursor; off by default for speed.
    humanlike: bool = False
    # Extra plugins for every run, such as a tracer.
    plugins: tuple[PluginLike, ...] = ()


async def run_task(
    task: Task, options: RunOptions, workspace: Path, attempt: int = 1
) -> TaskResult:
    """Return a record on execution or check failure; cancellation still propagates."""
    record = TaskResult(
        task=task.name,
        stage=task.stage,
        tags=list(task.tags),
        attempt=attempt,
        url=task.url,
        workspace=str(workspace),
        status="error",
        score=0.0,
        seconds=0.0,
    )
    phase: Literal["setup", "execution", "evidence", "checks"] = "setup"
    started = time.monotonic()
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        async with _agent(task, options, workspace).session() as session:
            record.session_id = session.id
            phase = "execution"
            result = await session.run(task.prompt, max_steps=task.max_steps)
            phase = "evidence"
            probes = await _read_probes(session.scope[Browser], task.probes)

        tools = _tool_calls(result.events)
        record.completed = result.completed
        record.stop_reason = str(result.stop_reason)
        record.answer = result.text
        record.probes = probes
        record.usage = Usage(
            input=result.usage.input_tokens,
            output=result.usage.output_tokens,
            cache_read=result.usage.cache_read_tokens,
            reasoning=result.usage.reasoning_tokens,
        )
        record.tool_calls = len(tools)
        record.tool_errors = sum(tool.error for tool in tools)
        record.tools = tools
        evidence = Evidence(
            answer=result.text,
            completed=result.completed,
            workspace=workspace,
            tools=tools,
            transcript="\n".join(
                [
                    *(repr(message) for message in result.messages),
                    *(json.dumps(tool.args, default=str) for tool in tools),
                ]
            ),
            probes=probes,
        )
        phase = "checks"
        checks = _evaluate_checks(task, evidence)
        reached = sum(check.ok for check in checks)
        record.checks = checks
        record.score = round(reached / len(checks), 3)
        record.status = (
            "pass" if result.completed and reached == len(checks) else "fail"
        )
        errors = [
            f"{check.label}: {check.error}"
            for check in checks
            if check.error is not None
        ]
        if errors:
            record.status = "error"
            record.error = "; ".join(errors)
            record.error_phase = "checks"
    except Exception as error:  # pylint: disable=broad-exception-caught
        record.status = "error"
        record.error = f"{type(error).__name__}: {error}"
        record.error_phase = phase
    finally:
        record.seconds = round(time.monotonic() - started, 1)
    return record


def _agent(task: Task, options: RunOptions, workspace: Path) -> Agent:
    # Provider dependencies are needed only when executing a live task.
    # pylint: disable=import-outside-toplevel
    from harnessed.models.pydantic_ai import PydanticAIModel

    plugins: list[PluginLike] = [
        Files(LocalWorkspace(workspace)),
        Approvals(default=PolicyDecision.ALLOW),
        *options.plugins,
    ]
    if task.secrets:
        plugins.append(Secrets(task.secrets))
    return Agent(
        model=PydanticAIModel(options.model),
        browser=Chrome.launch(url=task.url, headless=not options.headed),
        plugins=plugins,
        without=() if options.humanlike else (InputPacing, InputVisualization),
    )


async def _read_probes(
    browser: Browser, expressions: tuple[str, ...]
) -> dict[str, Any]:
    probes: dict[str, Any] = {}
    for expression in expressions:
        try:
            probes[expression] = json.loads(
                await browser.active_tab.evaluate(expression)
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            probes[expression] = {"probe_error": f"{type(error).__name__}: {error}"}
    return probes


def _tool_calls(events: Iterable[object]) -> list[ToolRecord]:
    calls: list[ToolRecord] = []
    for event in events:
        if not isinstance(event, ToolCallFinishedEvent):
            continue
        content = event.result.content
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        # Harnessed's schema turns frozen argument mappings and tuples back into JSON.
        call = _TOOL_CALL_ADAPTER.dump_python(event.call, mode="json")
        calls.append(
            ToolRecord(
                name=event.call.name,
                args=call["arguments"],
                error=event.result.is_error,
                chars=len(text),
                preview=text[:300],
            )
        )
    return calls


def _evaluate_checks(task: Task, evidence: Evidence) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for check in task.checks:
        try:
            miss = check.evaluate(evidence)
            checks.append(CheckResult(label=check.label, ok=miss is None, detail=miss))
        except Exception as error:  # pylint: disable=broad-exception-caught
            detail = f"{type(error).__name__}: {error}"
            checks.append(
                CheckResult(label=check.label, ok=False, detail=detail, error=detail)
            )
    return checks
