"""Pull each task's spans from Phoenix with the `px` CLI and report context efficiency.

uv run python -m evals.analyze evals/results/<run>.json [--dump]

Per task: steps, prompt growth, cache hit rate, what each step added to the context
(observations vs tool results) and the largest additions. --dump writes the final model
input and every step's new messages to evals/results/dumps/<run>/<task>.md for reading.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .results import BenchmarkResult, TaskResult

_LINK_LINE = re.compile(r"^\s*(?:[-*\d.]+\s*)?\[[^\]]*\]\(<?[^)]*>?\)\s*$")


def px_spans(project: str, session_id: str) -> list[dict]:
    command = [
        shutil.which("px") or "px",
        "span", "list", "--project", project, "--attribute", f"session.id:{session_id}",
        "--limit", "2000", "--format", "raw", "--no-progress",
    ]  # fmt: skip
    out = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return json.loads(out.stdout or "[]")


def analyze(record: TaskResult, project: str, dump_dir: Path | None) -> dict:
    if record.session_id is None:
        raise ValueError(f"{record.task}: no session to analyze")
    spans = px_spans(project, record.session_id)
    models = sorted(
        (s for s in spans if s["name"] == "harnessed.model"),
        key=lambda s: s["start_time"],
    )
    tools = [s for s in spans if s["name"] == "harnessed.tool"]
    steps, lines, noise = _analyze_steps(models, dump_dir is not None)
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        header = f"# {record.task}\n\n{record.answer or record.error or ''}\n"
        name = f"{record.task}-{record.attempt}"
        (dump_dir / f"{name}.md").write_text(
            header + "\n".join(lines), encoding="utf-8"
        )
    prompts = [step["prompt"] for step in steps]
    total = sum(prompts)
    cached = sum(step["cached"] for step in steps)
    tool_chars: dict[str, list[int]] = {}
    errors = []
    for span in tools:
        attrs = span["attributes"]
        name = attrs.get("tool.name", "?")
        tool_chars.setdefault(name, []).append(len(attrs.get("output.value") or ""))
        if str(attrs.get("harnessed.tool.is_error")).lower() == "true":
            errors.append(f"{name}: {(attrs.get('output.value') or '')[:160]}")
    observation_chars = [step["added"].get("observation", 0) for step in steps]
    return {
        "task": record.task,
        "attempt": record.attempt,
        "status": record.status,
        "passed": record.status == "pass",
        "trace_available": bool(spans),
        "steps": len(steps),
        "prompt_total": total,
        "prompt_max": max(prompts, default=0),
        "cache_hit": round(cached / total, 3) if total else None,
        "uncached_total": total - cached,
        "rewrites": sum(1 for step in steps if step["rewritten"]),
        "obs_avg": round(
            sum(observation_chars) / max(1, sum(1 for c in observation_chars if c))
        ),
        "obs_max": max(observation_chars, default=0),
        "tools": {
            name: (len(sizes), max(sizes)) for name, sizes in sorted(tool_chars.items())
        },
        "errors": errors,
        "noise": noise,
        "steps_detail": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--dump", action="store_true")
    args = parser.parse_args()
    run = BenchmarkResult.model_validate_json(args.results.read_text(encoding="utf-8"))
    dumps = args.results.parent / "dumps" / run.run if args.dump else None
    reports = []
    for record in run.tasks:
        if record.session_id is None:
            print(f"{record.task}: no session ({record.error})")
            continue
        report = analyze(record, run.project, dumps)
        reports.append(report)
        status = report["status"]
        print(
            f"\n{report['task']}#{report['attempt']} [{status}] steps={report['steps']} "
            f"prompt_total={report['prompt_total']} max={report['prompt_max']} "
            f"cache={report['cache_hit']} uncached={report['uncached_total']} "
            f"rewrites={report['rewrites']} obs_avg={report['obs_avg']} obs_max={report['obs_max']}"
        )
        print("  tools (calls, max chars):", report["tools"])
        if not report["trace_available"]:
            print("  no spans found for this session")
        missing = [check.label for check in record.checks if not check.ok]
        if missing:
            print("  missing:", missing)
        for error in report["errors"]:
            print("  error:", error)
        noisy = [
            n
            for n in report["noise"]
            if n["lines"] >= 10 and (n["repeat"] >= 0.5 or n["links"] >= 0.5)
        ]
        for n in noisy:
            print(
                f"  noise: step {n['step']} {n['kind']} lines={n['lines']} "
                f"repeat={n['repeat']} links={n['links']}"
            )
        for step in report["steps_detail"]:
            added = ", ".join(f"{k}={v}" for k, v in step["added"].items())
            print(
                f"    {step['step']:>2} prompt={step['prompt']:>6} uncached={step['uncached']:>6}"
                f" +[{added}] → {','.join(step['calls']) or 'answer'}"
            )
    out = args.results.with_suffix(".analysis.json")
    out.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAnalysis: {out}", file=sys.stderr)


def _analyze_steps(
    models: list[dict], dump: bool
) -> tuple[list[dict], list[str], list[dict]]:
    steps = []
    previous: list[dict] = []
    lines: list[str] = []
    seen: set[str] = set()
    noise: list[dict] = []
    call_names: dict[str, str] = {}
    for index, span in enumerate(models, 1):
        attrs = span["attributes"]
        prompt = attrs.get("llm.token_count.prompt") or 0
        cached = attrs.get("llm.token_count.prompt_details.cache_read") or 0
        messages = _messages(span)
        added: dict[str, int] = {}
        if messages is not None:
            added, rewritten, message_lines, message_noise = _context_delta(
                messages,
                previous,
                index,
                call_names,
                seen,
                dump_header=f"\n## step {index} · prompt {prompt} · cached {cached}"
                if dump
                else None,
            )
            lines.extend(message_lines)
            noise.extend(message_noise)
            previous = messages
        else:
            rewritten = None
        try:
            output = json.loads(attrs.get("output.value") or "{}")
        except json.JSONDecodeError:
            output = {}
        if not isinstance(output, dict):
            output = {}
        calls = [c["name"] for c in output.get("tool_calls") or []]
        steps.append(
            {
                "step": index,
                "prompt": prompt,
                "cached": cached,
                "uncached": prompt - cached,
                "added": added,
                "rewritten": rewritten,
                "calls": calls,
            }
        )
    return steps, lines, noise


def _context_delta(
    messages: list[dict],
    previous: list[dict],
    step: int,
    call_names: dict[str, str],
    seen: set[str],
    *,
    dump_header: str | None,
) -> tuple[dict[str, int], int, list[str], list[dict]]:
    # Append-only histories share the previous prefix; anything else is a rewrite.
    shared = 0
    while (
        shared < min(len(previous), len(messages))
        and previous[shared] == messages[shared]
    ):
        shared += 1
    rewritten = len(previous) - shared
    added: dict[str, int] = {}
    lines: list[str] = []
    noise: list[dict] = []
    if dump_header is not None:
        lines.append(
            dump_header + (f" · REWROTE {rewritten} messages" if rewritten else "")
        )
    for message in messages[shared:]:
        kind = _kind(message, call_names)
        text = _text(message)
        added[kind] = added.get(kind, 0) + len(text)
        if kind == "observation" or kind.startswith("tool:"):
            noise.append({"step": step, "kind": kind, **_noise(text, seen)})
        if dump_header is not None:
            lines.extend((f"\n### {kind} ({len(text)} chars)\n", f"```\n{text}\n```"))
    return added, rewritten, lines, noise


def _messages(span: dict) -> list[dict] | None:
    attrs = span["attributes"]
    if attrs.get("harnessed.input.truncated"):
        return None
    try:
        messages = json.loads(attrs.get("input.value") or "null")
    except json.JSONDecodeError:
        return None
    return messages if isinstance(messages, list) else None


def _text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return "\n".join(
            part.get("text", f"<{part.get('type', 'part')}>")
            if isinstance(part, dict)
            else str(part)
            for part in content
        )
    body = (
        content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    )
    calls = message.get("tool_calls") or []
    if calls:
        body += "\n" + "\n".join(
            f"→ {c['name']}({json.dumps(c.get('arguments'))})" for c in calls
        )
    return body


def _kind(message: dict, call_names: dict[str, str]) -> str:
    role = message.get("role", "?")
    for call in message.get("tool_calls") or []:
        call_names[call.get("id", "")] = call["name"]
    text = _text(message)
    if role == "user" and text.lstrip().startswith("# ") and "\nurl: " in text[:600]:
        return "observation"
    if role == "tool":
        return f"tool:{call_names.get(message.get('tool_call_id', ''), '?')}"
    return role


def _noise(text: str, seen: set[str]) -> dict[str, float]:
    """How much of a context addition repeats earlier lines or is only a link."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {"lines": 0, "repeat": 0.0, "links": 0.0}
    repeat = sum(line in seen for line in lines)
    links = sum(bool(_LINK_LINE.match(line)) for line in lines)
    seen.update(lines)
    return {
        "lines": len(lines),
        "repeat": round(repeat / len(lines), 2),
        "links": round(links / len(lines), 2),
    }


if __name__ == "__main__":
    main()
