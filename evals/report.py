"""Summarise a benchmark run and compare it with an earlier one.

uv run python -m evals.report evals/results/<run>.json [--against evals/results/<old>.json]
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

RESULTS = Path(__file__).with_name("results")


def _by_task(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["task"]].append(record)
    return grouped


def _task_line(name: str, attempts: list[dict]) -> str:
    passes = sum(r["status"] == "pass" for r in attempts)
    errors = sum(r["status"] == "error" for r in attempts)
    score = mean(r["score"] for r in attempts)
    seconds = mean(r.get("seconds") or 0 for r in attempts)
    mark = (
        "PASS"
        if passes == len(attempts)
        else ("ERR " if errors == len(attempts) else "FAIL")
    )
    misses = sorted(
        {c["label"] for r in attempts for c in r.get("checks", []) if not c["ok"]}
        | {r["error"][:60] for r in attempts if "error" in r}
    )
    tail = f"  missed: {', '.join(misses)}" if misses else ""
    runs = f"{passes}/{len(attempts)}"
    return f"  {mark} {name:<24} {runs}  score {score:4.0%}  {seconds:6.1f}s{tail}"


def _group_scores(records: list[dict], key) -> list[str]:
    scores: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for group in key(record):
            scores[group].append(record["score"])
    return [
        f"  {group:<16} {mean(values):4.0%}  ({len(values)} runs)"
        for group, values in sorted(scores.items(), key=lambda item: mean(item[1]))
    ]


def summary(run: dict[str, Any]) -> str:
    records = run["tasks"]
    usage = [r["usage"] for r in records if "usage" in r]
    lines = [f"Run {run['run']}  model {run['model']}", "", "Tasks"]
    for stage in ("practice", "reference", "wild"):
        grouped = {n: a for n, a in _by_task(records).items() if a[0]["stage"] == stage}
        if grouped:
            lines.append(f" {stage}")
            lines += [_task_line(name, attempts) for name, attempts in grouped.items()]
    # Crashes of the site or harness say nothing about the agent; keep them out of scores.
    scored = [r for r in records if r["status"] != "error"]
    lines += ["", "Stages (mean milestone score, errors excluded)"]
    lines += _group_scores(scored, lambda r: [r["stage"]])
    lines += ["", "Capabilities, weakest first"]
    lines += _group_scores(scored, lambda r: r["tags"])
    passed = sum(r["status"] == "pass" for r in records)
    errors = len(records) - len(scored)
    score = f"{mean(r['score'] for r in scored):.0%}" if scored else "n/a"
    lines += [
        "",
        f"Total  {passed}/{len(records)} passed, {errors} errors (site or harness), "
        f"mean score {score}",
        f"Tokens {sum(u['input'] for u in usage):,} in / {sum(u['output'] for u in usage):,} out, "
        f"{sum(r.get('seconds') or 0 for r in records):.0f}s agent time",
    ]
    return "\n".join(lines)


def compare(run: dict[str, Any], before: dict[str, Any]) -> str:
    now, then = _by_task(run["tasks"]), _by_task(before["tasks"])
    lines = [f"Compared with {before['run']} ({before['model']})"]
    changes = []
    for name in now.keys() & then.keys():
        score_now = mean(r["score"] for r in now[name])
        score_then = mean(r["score"] for r in then[name])
        if abs(score_now - score_then) >= 0.01:
            changes.append((score_now - score_then, name, score_then, score_now))
    if not changes:
        lines.append("  no score changes")
    for delta, name, old, new in sorted(changes):
        label = "WORSE" if delta < 0 else "better"
        lines.append(f"  {label:<6} {name:<24} {old:4.0%} -> {new:4.0%}")
    return "\n".join(lines)


def previous_run(current: Path) -> dict[str, Any] | None:
    """The latest earlier run that shares at least one task with `current`."""
    run = json.loads(current.read_text("utf-8"))
    names = {r["task"] for r in run["tasks"]}
    for path in sorted(RESULTS.glob("*.json"), reverse=True):
        if path.name >= current.name or path.name.endswith(".analysis.json"):
            continue
        try:
            earlier = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # Runs from the old format had no stages or scores.
        tasks = earlier.get("tasks", [])
        if tasks and "score" in tasks[0] and names & {r["task"] for r in tasks}:
            return earlier
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--against", type=Path, help="Default: the latest earlier run")
    args = parser.parse_args()
    run = json.loads(args.run.read_text("utf-8"))
    print(summary(run))
    before = (
        json.loads(args.against.read_text("utf-8"))
        if args.against
        else previous_run(args.run)
    )
    if before is not None:
        print()
        print(compare(run, before))


if __name__ == "__main__":
    main()
