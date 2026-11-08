"""Run benchmark tasks on live websites and report milestone scores.

uv run --env-file .env --extra openai python -m evals.run --tasks @practice
uv run --env-file .env --extra openai python -m evals.run --tasks saucedemo_checkout --headed
uv run --env-file .env --extra openai python -m evals.run --list

Prefer evals/bench.sh, which wraps these commands per stage.
"""

import argparse
import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from dotenv import load_dotenv
from harnessed.kernel import PluginLike

from . import report
from .runner import RunOptions, run_task
from .suites import TASKS, select
from .task import STAGES, Task

PROJECT = "browserrig-evals"


def _list_tasks() -> None:
    for stage in STAGES:
        print(stage)
        for task in (t for t in TASKS if t.stage == stage):
            print(
                f"  {task.name:<24} {len(task.checks)} checks  {', '.join(task.tags)}"
            )


@asynccontextmanager
async def _tracing(enabled: bool) -> AsyncIterator[tuple[PluginLike, ...]]:
    """Export traces to the local Phoenix project that evals.analyze reads."""
    if not enabled:
        yield ()
        return
    # pylint: disable=import-outside-toplevel - otel is an optional extra
    from harnessed.integrations.opentelemetry import OpenTelemetryTracer, otlp_provider

    async with otlp_provider(
        service_name="browserrig",
        endpoint="http://127.0.0.1:6006/v1/traces",
        resource_attributes={"openinference.project.name": PROJECT},
    ) as provider:
        yield (
            OpenTelemetryTracer(
                tracer_provider=provider,
                capture_content=True,
                max_content_length=400_000,
            ),
        )


async def _run_all(
    tasks: list[Task], options: RunOptions, run_name: str, repeat: int, parallel: int
) -> list[dict]:
    workspaces = report.RESULTS / "workspaces" / run_name
    gate = asyncio.Semaphore(parallel)

    async def one(task: Task, attempt: int) -> dict:
        async with gate:
            name = task.name if repeat == 1 else f"{task.name}#{attempt}"
            print(f"> {name}", flush=True)
            record = await run_task(
                task, options, workspaces / name.replace("#", "-"), attempt
            )
            detail = record.get("error", "")[:100]
            print(
                f"= {name}: {record['status']} {record['score']:.0%} "
                f"({record.get('seconds')}s) {detail}",
                flush=True,
            )
            return record

    return list(
        await asyncio.gather(
            *(one(task, attempt) for task in tasks for attempt in range(1, repeat + 1))
        )
    )


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tasks", help="Names, @stage or @tag, comma-separated; default: all"
    )
    parser.add_argument("--list", action="store_true", help="List tasks and exit")
    parser.add_argument(
        "--repeat", type=int, default=1, help="Runs per task, to see flakiness"
    )
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--humanlike", action="store_true", help="Keep input pacing and cursor"
    )
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-6.1-terra"))
    parser.add_argument("--label", default="", help="Suffix for the results file")
    parser.add_argument(
        "--trace", action="store_true", help="Export traces to local Phoenix"
    )
    args = parser.parse_args()
    if args.list:
        _list_tasks()
        return
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY in the environment or in .env")

    tasks = select(args.tasks)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_name = f"{stamp}{'-' + args.label if args.label else ''}"
    async with _tracing(args.trace) as tracer:
        options = RunOptions(
            model=args.model,
            headed=args.headed,
            humanlike=args.humanlike,
            plugins=tracer,
        )
        records = await _run_all(tasks, options, run_name, args.repeat, args.parallel)

    run = {
        "run": run_name,
        "model": args.model,
        "selection": args.tasks or "all",
        "repeat": args.repeat,
        "project": PROJECT,
        "tasks": records,
    }
    report.RESULTS.mkdir(exist_ok=True)
    out = report.RESULTS / f"{run_name}.json"
    out.write_text(
        json.dumps(run, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print()
    print(report.summary(run))
    if (before := report.previous_run(out)) is not None:
        print()
        print(report.compare(run, before))
    print(f"\nResults: {out}")


if __name__ == "__main__":
    asyncio.run(main())
