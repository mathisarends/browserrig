"""Run live-site tasks with tracing into the Phoenix project `browserrig-evals`.

docker compose up -d --wait
uv run --extra openai --extra otel python -m evals.run --tasks wiki_mountains,@landing
uv run --extra openai --extra otel python -m evals.analyze evals/results/<run>.json
"""

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from harnessed import PolicyDecision
from harnessed.events import ToolCallFinishedEvent, ToolCallRequestedEvent
from harnessed.integrations.opentelemetry import OpenTelemetryTracer, otlp_provider
from harnessed.models.pydantic_ai import PydanticAIModel
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel

from browserrig import Agent, FileSystemOptions, Launch

from .tasks import Task, select

PROJECT = "browserrig-evals"
RESULTS = Path(__file__).with_name("results")


async def run_task(
    task: Task, *, provider, model_name: str, workspace: Path, headed: bool
) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    agent = Agent(
        model=PydanticAIModel(OpenAIResponsesModel(model_name)),
        browser=Launch(
            url=task.url,
            headless=not headed,
            files=FileSystemOptions(directory=workspace),
        ),
        plugins=[
            Approvals(default=PolicyDecision.ALLOW),
            OpenTelemetryTracer(
                tracer_provider=provider,
                capture_content=True,
                max_content_length=400_000,
            ),
        ],
    )
    started = time.monotonic()
    record: dict = {"task": task.name, "url": task.url, "tags": list(task.tags)}
    try:
        async with agent.session() as session:
            record["session_id"] = session.id
            result = await session.run(task.prompt, max_steps=task.max_steps)
    except Exception as error:  # noqa: BLE001 - one broken site must not stop the suite
        record.update(
            error=f"{type(error).__name__}: {error}", seconds=time.monotonic() - started
        )
        return record
    requested = {
        e.call.id: e.call
        for e in result.events
        if isinstance(e, ToolCallRequestedEvent)
    }
    tools = []
    for event in result.events:
        if isinstance(event, ToolCallFinishedEvent) and event.call_id in requested:
            call = requested[event.call_id]
            content = event.result.content
            text = (
                content
                if isinstance(content, str)
                else json.dumps(content, default=str)
            )
            tools.append(
                {
                    "name": call.name,
                    "args": call.arguments,
                    "error": event.result.is_error,
                    "chars": len(text),
                    "preview": text[:300],
                }
            )
    usage = result.usage
    missing = task.check(result.text)
    record.update(
        seconds=round(time.monotonic() - started, 1),
        stop_reason=str(result.stop_reason),
        answer=result.text,
        passed=result.completed and not missing,
        missing=missing,
        usage={
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "cache_read": usage.cache_read_tokens,
            "reasoning": usage.reasoning_tokens,
        },
        tools=tools,
    )
    return record


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", help="Comma-separated names or @tag; default: all")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    parser.add_argument("--label", default="", help="Suffix for the results file")
    args = parser.parse_args()
    tasks = select(args.tasks)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_name = f"{stamp}{'-' + args.label if args.label else ''}"
    workspaces = RESULTS / "workspaces" / run_name
    gate = asyncio.Semaphore(args.parallel)

    async with otlp_provider(
        service_name="browserrig",
        endpoint="http://127.0.0.1:6006/v1/traces",
        resource_attributes={"openinference.project.name": PROJECT},
    ) as provider:

        async def guarded(task: Task) -> dict:
            async with gate:
                print(f"> {task.name}", flush=True)
                record = await run_task(
                    task,
                    provider=provider,
                    model_name=args.model,
                    workspace=workspaces / task.name,
                    headed=args.headed,
                )
                status = (
                    "ERROR"
                    if "error" in record
                    else ("pass" if record["passed"] else "FAIL")
                )
                print(f"= {task.name}: {status} ({record.get('seconds')}s)", flush=True)
                return record

        records = await asyncio.gather(*(guarded(task) for task in tasks))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{run_name}.json"
    out.write_text(
        json.dumps(
            {
                "run": run_name,
                "model": args.model,
                "project": PROJECT,
                "tasks": records,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nResults: {out}")


if __name__ == "__main__":
    asyncio.run(main())
