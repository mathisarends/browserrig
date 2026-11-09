"""Summarise a benchmark run and compare it with an earlier one.

uv run python -m evals.report evals/results/<run>.json [--against evals/results/<old>.json]
"""

import argparse
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from statistics import mean

from pydantic import ValidationError

from .results import BenchmarkResult, TaskResult
from .task import STAGES

RESULTS = Path(__file__).with_name("results")


def summary(run: BenchmarkResult) -> str:
    records = run.tasks
    usage = [r.usage for r in records if r.usage is not None]
    lines = [f"Run {run.run}  model {run.model}  provider {run.provider}", "", "Tasks"]
    for stage in STAGES:
        grouped = {n: a for n, a in _by_task(records).items() if a[0].stage == stage}
        if grouped:
            lines.append(f" {stage}")
            lines += [_task_line(name, attempts) for name, attempts in grouped.items()]
    # Execution and evaluator errors have no reliable agent score.
    scored = [r for r in records if r.status != "error"]
    lines += ["", "Stages (mean milestone score, errors excluded)"]
    lines += _group_scores(scored, lambda r: [r.stage])
    lines += ["", "Capabilities, weakest first"]
    lines += _group_scores(scored, lambda r: r.tags)
    passed = sum(r.status == "pass" for r in records)
    errors = len(records) - len(scored)
    score = f"{mean(r.score for r in scored):.0%}" if scored else "n/a"
    lines += [
        "",
        f"Total  {passed}/{len(records)} passed, {errors} errors (execution or checks), "
        f"mean score {score}",
        f"Tokens {sum(u.input for u in usage):,} in / {sum(u.output for u in usage):,} out, "
        f"{sum(record.seconds for record in records):.0f}s agent time",
    ]
    return "\n".join(lines)


def compare(run: BenchmarkResult, before: BenchmarkResult) -> str:
    now, then = _by_task(run.tasks), _by_task(before.tasks)
    lines = [f"Compared with {before.run} ({before.provider}:{before.model})"]
    changes = []
    comparable = 0
    for name in sorted(now.keys() & then.keys()):
        errors_now = sum(r.status == "error" for r in now[name])
        errors_then = sum(r.status == "error" for r in then[name])
        if errors_now or errors_then:
            lines.append(
                f"  errors {name:<24} {errors_then}/{len(then[name])} -> "
                f"{errors_now}/{len(now[name])} (excluded from scores)"
            )
        score_now = _mean_score(now[name])
        score_then = _mean_score(then[name])
        if score_now is None or score_then is None:
            lines.append(f"  skip   {name:<24} no scored attempts on both sides")
            continue
        comparable += 1
        if abs(score_now - score_then) >= 0.01:
            changes.append((score_now - score_then, name, score_then, score_now))
    if not changes:
        lines.append(
            "  no score changes" if comparable else "  no comparable scored tasks"
        )
    for delta, name, old, new in sorted(changes):
        label = "WORSE" if delta < 0 else "better"
        lines.append(f"  {label:<6} {name:<24} {old:4.0%} -> {new:4.0%}")
    return "\n".join(lines)


def previous_run(current: Path) -> BenchmarkResult | None:
    """The latest earlier run that shares at least one task with `current`."""
    run = BenchmarkResult.model_validate_json(current.read_text("utf-8"))
    names = {r.task for r in run.tasks}
    for path in sorted(RESULTS.glob("*.json"), reverse=True):
        if path.name >= current.name or path.name.endswith(".analysis.json"):
            continue
        try:
            earlier = BenchmarkResult.model_validate_json(path.read_text("utf-8"))
        except (ValidationError, OSError):
            continue
        if names & {record.task for record in earlier.tasks}:
            return earlier
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--against", type=Path, help="Default: the latest earlier run")
    args = parser.parse_args()
    run = BenchmarkResult.model_validate_json(args.run.read_text("utf-8"))
    print(summary(run))
    before = (
        BenchmarkResult.model_validate_json(args.against.read_text("utf-8"))
        if args.against
        else previous_run(args.run)
    )
    if before is not None:
        print()
        print(compare(run, before))


def _by_task(records: list[TaskResult]) -> dict[str, list[TaskResult]]:
    grouped: dict[str, list[TaskResult]] = defaultdict(list)
    for record in records:
        grouped[record.task].append(record)
    return grouped


def _task_line(name: str, attempts: list[TaskResult]) -> str:
    passes = sum(r.status == "pass" for r in attempts)
    errors = sum(r.status == "error" for r in attempts)
    score = _mean_score(attempts)
    score_text = f"{score:4.0%}" if score is not None else " n/a"
    seconds = mean(r.seconds or 0 for r in attempts)
    mark = "ERR " if errors else ("PASS" if passes == len(attempts) else "FAIL")
    misses = sorted(
        {c.label for r in attempts for c in r.checks if not c.ok}
        | {r.error[:60] for r in attempts if r.error is not None}
    )
    tail = f"  missed: {', '.join(misses)}" if misses else ""
    runs = f"{passes}/{len(attempts)}"
    return f"  {mark} {name:<24} {runs}  score {score_text}  {seconds:6.1f}s{tail}"


def _group_scores(
    records: list[TaskResult], key: Callable[[TaskResult], Iterable[str]]
) -> list[str]:
    scores: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for group in key(record):
            scores[group].append(record.score)
    return [
        f"  {group:<16} {mean(values):4.0%}  ({len(values)} runs)"
        for group, values in sorted(scores.items(), key=lambda item: mean(item[1]))
    ]


def _mean_score(records: list[TaskResult]) -> float | None:
    scores = [record.score for record in records if record.status != "error"]
    return mean(scores) if scores else None


if __name__ == "__main__":
    main()
