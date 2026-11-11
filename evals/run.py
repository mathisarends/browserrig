"""Run the frozen 48-task WebArena-Verified Hard subset with Browserrig."""

import argparse
import asyncio
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from browserrig.core import MODEL_PROFILES

from . import report
from .environments import DEFAULT_CONFIG, DEFAULT_DATA, Environments
from .results import BenchmarkResult, write_run
from .runner import RunOptions, run_task
from .task import Task, load_tasks, select
from .telemetry import DEFAULT_PROJECT, tracing_plugins


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks",
        help="Frozen IDs or @site/@retrieve/@mutate/@navigate, comma-separated",
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Preflight only; no model calls"
    )
    parser.add_argument("--repeat", type=_positive_int, default=1)
    parser.add_argument("--parallel", type=_positive_int, default=1)
    parser.add_argument("--max-steps", type=_positive_int, default=50)
    parser.add_argument(
        "--timeout", type=_positive_int, default=300, help="Agent seconds per task"
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--humanlike", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument(
        "--provider", choices=("openai-codex", "openai"), default="openai-codex"
    )
    parser.add_argument(
        "--model", help="Default: gpt-6.1-terra; openai also reads OPENAI_MODEL"
    )
    parser.add_argument("--label", default="")
    parser.add_argument("--trace", action="store_true", help="Export traces to Phoenix")
    return parser


async def main() -> None:
    load_dotenv()
    parser = _parser()
    args = parser.parse_args()
    if args.parallel != 1:
        parser.error("WebArena shares mutable sites: --parallel must be 1")
    try:
        manifest, frozen = load_tasks()
        tasks = select(frozen, args.tasks)
    except ValueError as error:
        parser.error(str(error))
    if args.list:
        for task in tasks:
            print(
                f"{task.name:>3}  {'+'.join(task.sites):<24} {task.action:<8} {task.intent}"
            )
        print(f"\n{len(tasks)} tasks; {manifest.name}; SHA-256 {manifest.tasks_sha256}")
        return
    if (
        not args.check
        and args.provider == "openai"
        and not os.environ.get("OPENAI_API_KEY")
    ):
        parser.error("Set OPENAI_API_KEY in the environment or in .env")

    environments = Environments(args.config, args.data_dir)
    # The fixed upstream container names are shared across processes and subsets.
    # pylint: disable=import-outside-toplevel
    from filelock import FileLock, Timeout

    lock = DEFAULT_DATA.parent / "webarena.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lock, timeout=0):
            try:
                await preflight(tasks, environments)
            except (OSError, RuntimeError, ValueError) as error:
                parser.error(
                    f"WebArena is not ready: {error}. "
                    "Prepare sites with python -m evals.environments prepare"
                )
            if args.check:
                print("Preflight passed; no model calls made.")
                return
            model_name, model = _model(args, parser)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
            run_name = f"{stamp}{'-' + args.label if args.label else ''}"
            project = os.getenv("PHOENIX_PROJECT_NAME", DEFAULT_PROJECT)
            profile = MODEL_PROFILES.get(model_name)
            benchmark = BenchmarkResult(
                run=run_name,
                model=model_name,
                provider=args.provider,
                selection=args.tasks or "all",
                repeat=args.repeat,
                project=project,
                subset=manifest.name,
                dataset_sha256=manifest.tasks_sha256,
                upstream_revision=manifest.revision,
                upstream_version=manifest.version,
                max_steps=args.max_steps,
                timeout=args.timeout,
                tasks=[],
                **(asdict(profile) if profile is not None else {}),
            )
            output = report.RESULTS / f"{run_name}.json"
            write_run(output, benchmark)
            async with tracing_plugins(args.trace, project) as plugins:
                options = RunOptions(
                    model,
                    args.headed,
                    args.humanlike,
                    plugins,
                    args.max_steps,
                    args.timeout,
                )
                await run_tasks(
                    tasks,
                    options,
                    benchmark,
                    output,
                    args.parallel,
                    environments=environments,
                )
    except Timeout as error:
        parser.error(f"Another WebArena process holds {lock}: {error}")
    print("\n" + report.summary(benchmark))
    if (before := report.previous_run(output)) is not None:
        print("\n" + report.compare(benchmark, before))
    print(f"\nResults: {output}")


async def preflight(tasks: list[Task], environments: Environments) -> None:
    await environments.check(
        {site for task in tasks for site in task.sites},
        DEFAULT_DATA.parent / "webarena-preflight.log",
    )


def _model(args, parser):
    # Resolve once to share the subscription provider's OAuth state.
    # pylint: disable=import-outside-toplevel
    from pydantic_ai.exceptions import UserError
    from pydantic_ai.models import infer_model

    name = args.model or (
        os.getenv("OPENAI_MODEL", "gpt-6.1-terra")
        if args.provider == "openai"
        else "gpt-6.1-terra"
    )
    prefix = "openai-responses" if args.provider == "openai" else args.provider
    try:
        return name, infer_model(f"{prefix}:{name}")
    except UserError as error:
        return parser.error(str(error))


async def run_tasks(
    tasks: list[Task],
    options: RunOptions,
    run: BenchmarkResult,
    output: Path,
    parallel: int = 1,
    *,
    environments: Environments | None = None,
) -> None:
    if parallel != 1:
        raise ValueError("WebArena shares mutable sites: parallel must be 1")
    workspaces = output.parent / "workspaces" / run.run
    for task in tasks:
        for attempt in range(1, run.repeat + 1):
            print(f"> {task.name} attempt {attempt}", flush=True)
            workspace = workspaces / f"attempt-{attempt}" / task.name
            record = await run_task(task, options, workspace, attempt, environments)
            run.tasks.append(record)
            write_run(output, run)
            print(
                f"= {task.name}: {record.status} {record.score:.0%} "
                f"({record.seconds}s) {(record.error or '')[:100]}",
                flush=True,
            )


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


if __name__ == "__main__":
    asyncio.run(main())
