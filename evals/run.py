"""Run benchmark tasks on live websites and report milestone scores.

uv run --env-file .env --extra openai python -m evals.run --tasks @practice
uv run --env-file .env --extra openai python -m evals.run --tasks saucedemo_checkout --headed
uv run --env-file .env --extra openai python -m evals.run --list

Prefer evals/bench.sh, which wraps these commands per stage.
"""

import argparse
import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from . import report
from .results import BenchmarkResult, write_run
from .runner import RunOptions, run_task
from .suites import TASKS, select
from .task import STAGES, Task
from .telemetry import DEFAULT_PROJECT, tracing_plugins


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
        "--repeat",
        type=_positive_int,
        default=1,
        help="Runs per task, to see flakiness",
    )
    parser.add_argument("--parallel", type=_positive_int, default=3)
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
    if not tasks:
        parser.error("Select at least one task")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    run_name = f"{stamp}{'-' + args.label if args.label else ''}"
    project = os.getenv("PHOENIX_PROJECT_NAME", DEFAULT_PROJECT)
    run = BenchmarkResult(
        run=run_name,
        model=args.model,
        selection=args.tasks or "all",
        repeat=args.repeat,
        project=project,
        tasks=[],
    )
    out = report.RESULTS / f"{run_name}.json"
    write_run(out, run)
    async with tracing_plugins(args.trace, project) as tracer:
        options = RunOptions(
            model=args.model,
            headed=args.headed,
            humanlike=args.humanlike,
            plugins=tracer,
        )
        await run_tasks(tasks, options, run, out, args.parallel)
    print()
    print(report.summary(run))
    if (before := report.previous_run(out)) is not None:
        print()
        print(report.compare(run, before))
    print(f"\nResults: {out}")


async def run_tasks(
    tasks: list[Task],
    options: RunOptions,
    run: BenchmarkResult,
    output: Path,
    parallel: int,
) -> None:
    if parallel < 1:
        raise ValueError("parallel must be at least 1")
    workspaces = output.parent / "workspaces" / run.run
    gate = asyncio.Semaphore(parallel)
    order = {task.name: index for index, task in enumerate(tasks)}

    async def one(task: Task, attempt: int) -> None:
        async with gate:
            name = task.name if run.repeat == 1 else f"{task.name}#{attempt}"
            print(f"> {name}", flush=True)
            record = await run_task(
                task, options, workspaces / name.replace("#", "-"), attempt
            )
            run.tasks.append(record)
            run.tasks.sort(key=lambda item: (order[item.task], item.attempt))
            write_run(output, run)
            detail = (record.error or "")[:100]
            print(
                f"= {name}: {record.status} {record.score:.0%} "
                f"({record.seconds}s) {detail}",
                flush=True,
            )

    pending = [
        asyncio.create_task(one(task, attempt))
        for task in tasks
        for attempt in range(1, run.repeat + 1)
    ]
    try:
        await asyncio.gather(*pending)
    finally:
        for job in pending:
            if not job.done():
                job.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def _list_tasks() -> None:
    for stage in STAGES:
        print(stage)
        for task in (t for t in TASKS if t.stage == stage):
            print(
                f"  {task.name:<24} {len(task.checks)} checks  {', '.join(task.tags)}"
            )


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


if __name__ == "__main__":
    asyncio.run(main())
