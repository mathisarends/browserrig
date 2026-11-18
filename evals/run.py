"""Run the frozen 48-task WebArena-Verified Hard subset with Browserrig."""

import argparse
import asyncio
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from harnessed import Plugin

from browserrig import (
    Actions,
    DomScrollTools,
    DomTypingTools,
    FormTools,
    JavaScriptTools,
    NetworkQuiet,
    Nudges,
    PageSearchTools,
    Readiness,
    ScreenshotCapture,
    ScreenshotTools,
    WheelTools,
    WorkspaceTools,
)
from browserrig.core import MODEL_PROFILES
from browserrig.observation import (
    BrowserPerception,
    CaptureStrategy,
    DomCapture,
    DomRenderer,
    Screenshots,
    ScreenshotTrigger,
    SetOfMarks,
    TextObservations,
)
from browserrig.readiness import BrowserReady

from . import report
from .environments import DEFAULT_CONFIG, DEFAULT_DATA, Environments
from .freeze import SUBSETS
from .results import BenchmarkResult, write_run
from .runner import RunOptions, run_task
from .task import Task, load_tasks, select
from .telemetry import DEFAULT_PROJECT, tracing_plugins

_OBSERVATION_MODES = (
    "text",
    "screenshot",
    "screenshot-marks",
    "text-screenshot",
    "text-screenshot-marks",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subset",
        choices=tuple(SUBSETS),
        default="local-v3",
        help="Default: local-v3 (48 tasks on provisioned sites); original-v1 is historical",
    )
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
    parser.add_argument(
        "--observation",
        choices=_OBSERVATION_MODES,
        help="Observation variant. If omitted, keep the historical text and on-request marks.",
    )
    parser.add_argument(
        "--screenshot-trigger",
        type=ScreenshotTrigger,
        choices=tuple(ScreenshotTrigger),
        help="Explicit image variants default to each_step.",
    )
    parser.add_argument(
        "--screenshot-tool",
        action=argparse.BooleanOptionalAction,
        help="Expose the screenshot tool. Defaults to enabled for on_request.",
    )
    parser.add_argument(
        "--page-text",
        choices=("inline", "sparse", "off"),
        default="inline",
        help="Prose in observations; compare arms such as inline and off",
    )
    parser.add_argument("--no-headings", dest="headings", action="store_false")
    parser.add_argument("--no-landmarks", dest="landmarks", action="store_false")
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
    perception, screenshot_tool = _perception(args, parser)
    try:
        manifest, frozen = load_tasks(SUBSETS[args.subset])
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
                page_text=args.page_text,
                headings=args.headings,
                landmarks=args.landmarks,
                observation_mode=args.observation,
                screenshot_trigger=perception.screenshots.trigger
                if perception.screenshots
                else None,
                screenshot_tool=screenshot_tool,
                tasks=[],
                **(asdict(profile) if profile is not None else {}),
            )
            output = report.RESULTS / f"{run_name}.json"
            write_run(output, benchmark)
            async with tracing_plugins(args.trace, project) as plugins:
                inputs = (
                    ()
                    if perception.text is not None
                    else (Actions(), WheelTools(), WorkspaceTools())
                )
                options = RunOptions(
                    model,
                    args.headed,
                    args.humanlike,
                    (
                        *plugins,
                        perception,
                        *inputs,
                        *_pixel_readiness(args.observation),
                    ),
                    args.max_steps,
                    args.timeout,
                    without=_excluded_tools(
                        perception, screenshot_tool=screenshot_tool
                    ),
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


def _perception(args, parser) -> tuple[BrowserPerception, bool]:
    mode = args.observation
    text = None
    if mode is None or mode.startswith("text"):
        text = TextObservations(mode="delta" if mode is None else "full")
    capture: CaptureStrategy = ScreenshotCapture()
    marks = SetOfMarks() if mode is None or mode.endswith("-marks") else None
    if text is not None or marks is not None:
        capture = DomCapture(
            page_prose=args.page_text, headings=args.headings, landmarks=args.landmarks
        )
    if mode == "text":
        if args.screenshot_trigger is not None or args.screenshot_tool:
            parser.error("Screenshot options require an image observation variant")
        return BrowserPerception(
            text=text, capture=capture, renderer=DomRenderer()
        ), False
    default = (
        ScreenshotTrigger.ON_REQUEST if mode is None else ScreenshotTrigger.EACH_STEP
    )
    trigger = args.screenshot_trigger or default
    enabled = args.screenshot_tool
    if enabled is None:
        enabled = trigger == ScreenshotTrigger.ON_REQUEST
    if trigger == ScreenshotTrigger.ON_REQUEST and not enabled:
        parser.error("on_request requires the screenshot tool")
    screenshots = Screenshots(trigger=trigger, marks=marks, skip_unchanged=mode is None)
    return BrowserPerception(
        text=text,
        screenshots=screenshots,
        capture=capture,
        renderer=DomRenderer() if text else None,
    ), enabled


def _pixel_readiness(observation: str | None) -> tuple[Readiness, ...]:
    if observation != "screenshot":
        return ()
    policy = NetworkQuiet(inner=BrowserReady())
    return (Readiness(initial=policy, ongoing=policy),)


def _excluded_tools(
    perception: BrowserPerception, *, screenshot_tool: bool
) -> tuple[type[Plugin], ...]:
    screenshot = () if screenshot_tool else (ScreenshotTools,)
    if perception.text is not None:
        return screenshot
    return (
        *screenshot,
        DomTypingTools,
        DomScrollTools,
        FormTools,
        JavaScriptTools,
        Nudges,
        PageSearchTools,
    )


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


if __name__ == "__main__":
    asyncio.run(main())
