"""Run one task in its own browser and workspace and score its milestones."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harnessed import PolicyDecision
from harnessed.events import ToolCallFinishedEvent
from harnessed.kernel import PluginLike
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

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
from .task import Task


@dataclass(frozen=True)
class RunOptions:
    model: str
    headed: bool = False
    # Keep human-like input pacing and the on-page cursor; off by default for speed.
    humanlike: bool = False
    # Extra plugins for every run, such as a tracer.
    plugins: tuple[PluginLike, ...] = ()


def _agent(task: Task, options: RunOptions, workspace: Path) -> Agent:
    plugins: list[PluginLike] = [
        Files(LocalWorkspace(workspace)),
        Approvals(default=PolicyDecision.ALLOW),
        *options.plugins,
    ]
    if task.secrets:
        plugins.append(Secrets(task.secrets))
    return Agent(
        model=PydanticAIModel(OpenAIResponsesModel(options.model)),
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
        except Exception as error:  # noqa: BLE001 - a failed probe is a missed milestone
            probes[expression] = {"probe_error": f"{type(error).__name__}: {error}"}
    return probes


def _tool_calls(events) -> list[dict[str, Any]]:
    calls = []
    for event in events:
        if not isinstance(event, ToolCallFinishedEvent):
            continue
        content = event.result.content
        text = content if isinstance(content, str) else json.dumps(content, default=str)
        calls.append(
            {
                "name": event.call.name,
                "args": event.call.arguments,
                "error": event.result.is_error,
                "chars": len(text),
                "preview": text[:300],
            }
        )
    return calls


async def run_task(
    task: Task, options: RunOptions, workspace: Path, attempt: int = 1
) -> dict[str, Any]:
    """Run `task` once; the record always has a status, even when the run crashed."""
    workspace.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "task": task.name,
        "stage": task.stage,
        "tags": list(task.tags),
        "attempt": attempt,
        "url": task.url,
        "workspace": str(workspace),
    }
    started = time.monotonic()
    try:
        async with _agent(task, options, workspace).session() as session:
            record["session_id"] = session.id
            result = await session.run(task.prompt, max_steps=task.max_steps)
            probes = await _read_probes(session.scope[Browser], task.probes)
    except Exception as error:  # noqa: BLE001 - one broken site must not stop the suite
        record.update(
            status="error",
            score=0.0,
            error=f"{type(error).__name__}: {error}",
            seconds=round(time.monotonic() - started, 1),
        )
        return record

    tools = _tool_calls(result.events)
    evidence = Evidence(
        answer=result.text,
        completed=result.completed,
        workspace=workspace,
        tools=tools,
        transcript="\n".join(
            [
                *(repr(m) for m in result.messages),
                *(json.dumps(t["args"], default=str) for t in tools),
            ]
        ),
        probes=probes,
    )
    checks = []
    for check in task.checks:
        miss = check.evaluate(evidence)
        checks.append({"label": check.label, "ok": miss is None, "detail": miss})
    reached = sum(c["ok"] for c in checks)
    passed = result.completed and reached == len(checks)
    usage = result.usage
    record.update(
        status="pass" if passed else "fail",
        score=round(reached / len(checks), 3),
        seconds=round(time.monotonic() - started, 1),
        completed=result.completed,
        stop_reason=str(result.stop_reason),
        answer=result.text,
        checks=checks,
        probes=probes,
        usage={
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cache_read": usage.cache_read_tokens,
            "reasoning": usage.reasoning_tokens,
        },
        tool_calls=len(tools),
        tool_errors=sum(t["error"] for t in tools),
        tools=tools,
    )
    return record
