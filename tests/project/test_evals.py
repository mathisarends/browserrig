"""Offline regression checks for benchmark execution, reports and trace analysis."""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from harnessed import ToolCall, ToolResult
from harnessed.events import ToolCallFinishedEvent

from browserrig.browser import Browser
from evals import analyze, report, run, runner
from evals.checks import Custom, ToolUsed
from evals.results import BenchmarkResult, CheckResult, TaskResult, Usage, write_run
from evals.task import Task, answer


@pytest.fixture(name="agent_result")
def prepared_agent_result(monkeypatch):
    result = SimpleNamespace(
        text="done",
        completed=True,
        stop_reason="completed",
        events=[],
        messages=[],
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=2, cache_read_tokens=4, reasoning_tokens=1
        ),
    )

    async def execute(*_args, **_kwargs):
        return result

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(id="session", run=execute, scope={Browser: None})

    monkeypatch.setattr(
        runner, "_agent", lambda *_args: SimpleNamespace(session=session)
    )
    return result


@pytest.mark.parametrize(
    ("completed", "expected_status"), [(True, "pass"), (False, "fail")]
)
async def test_run_requires_completion_even_when_checks_pass(
    tmp_path, agent_result, completed, expected_status
):
    agent_result.completed = completed
    result = await runner.run_task(_task("demo"), runner.RunOptions("test"), tmp_path)

    assert result.status == expected_status
    assert result.score == 1.0
    assert result.usage.input == 10


async def test_check_errors_preserve_evidence_and_do_not_skip_other_checks(
    tmp_path, agent_result
):
    def broken_check(_evidence):
        raise ValueError("invalid evaluator")

    task = _task("demo", (Custom("broken", broken_check), answer("done")))
    result = await runner.run_task(task, runner.RunOptions("test"), tmp_path)

    assert result.status == "error"
    assert result.error_phase == "checks"
    assert result.answer == agent_result.text
    assert result.usage.output == 2
    assert result.score == 0.5
    assert result.checks[0].error == "ValueError: invalid evaluator"
    assert result.checks[1].ok is True


async def test_tool_evidence_serializes_harnessed_arguments(tmp_path, agent_result):
    agent_result.events = [
        ToolCallFinishedEvent(
            call=ToolCall(
                "upload_files", {"paths": ["note.txt"], "options": {"mode": "test"}}
            ),
            result=ToolResult("uploaded"),
        )
    ]
    task = _task("demo", (ToolUsed("upload", "upload_files"),))

    result = await runner.run_task(task, runner.RunOptions("test"), tmp_path)
    saved = json.loads(result.model_dump_json())

    assert result.status == "pass", result.error
    assert result.tool_calls == 1
    assert saved["tools"][0]["args"] == {
        "paths": ["note.txt"],
        "options": {"mode": "test"},
    }


async def test_workspace_setup_failure_becomes_a_task_error(tmp_path):
    workspace = tmp_path / "file"
    workspace.write_text("occupied", encoding="utf-8")

    result = await runner.run_task(_task("demo"), runner.RunOptions("test"), workspace)

    assert result.status == "error"
    assert result.error_phase == "setup"
    assert "FileExistsError" in result.error


async def test_run_cancellation_is_not_reported_as_a_task_error(tmp_path, monkeypatch):
    def cancel(*_args):
        raise asyncio.CancelledError

    monkeypatch.setattr(runner, "_agent", cancel)
    with pytest.raises(asyncio.CancelledError):
        await runner.run_task(_task("demo"), runner.RunOptions("test"), tmp_path)


def test_reports_exclude_errors_consistently_and_show_error_counts():
    before = _benchmark([_record("demo")])
    current = _benchmark([_record("demo"), _record("demo", "error", 0.0)])

    summary = report.summary(current)
    comparison = report.compare(current, before)

    assert "score 100%" in summary
    assert "mean score 100%" in summary
    assert "WORSE" not in comparison
    assert "0/1 -> 1/2 (excluded from scores)" in comparison
    assert "no score changes" in comparison


def test_reports_do_not_invent_a_score_when_all_attempts_error():
    current = _benchmark([_record("demo", "error", 0.0)])

    assert "score  n/a" in report.summary(current)
    assert "mean score n/a" in report.summary(current)
    comparison = report.compare(current, _benchmark([_record("demo")]))
    assert "no comparable scored tasks" in comparison
    assert "WORSE" not in comparison


def test_comparison_still_reports_real_regressions():
    current = _benchmark([_record("demo", "fail", 0.5)])

    comparison = report.compare(current, _benchmark([_record("demo")]))

    assert "WORSE" in comparison
    assert "100% ->  50%" in comparison


def test_analysis_uses_current_status_and_keeps_repetition_dumps(tmp_path, monkeypatch):
    monkeypatch.setattr(analyze, "px_spans", lambda *_args: [])
    for attempt in (1, 2):
        record = _record("demo")
        record.attempt = attempt
        result = analyze.analyze(record, "test", tmp_path)
        assert result["status"] == "pass"
        assert result["passed"] is True
        assert result["trace_available"] is False

    assert {path.name for path in tmp_path.glob("*.md")} == {"demo-1.md", "demo-2.md"}


def test_analysis_does_not_reuse_tool_names_between_sessions(monkeypatch):
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "call", "name": "click"}]},
        {"role": "tool", "tool_call_id": "call", "content": "done"},
    ]
    spans = [_model_span(messages)]
    monkeypatch.setattr(analyze, "px_spans", lambda *_args: spans)

    first = analyze.analyze(_record("first"), "test", None)
    spans[:] = [_model_span(messages[1:])]
    second = analyze.analyze(_record("second"), "test", None)

    assert "tool:click" in first["steps_detail"][0]["added"]
    assert "tool:?" in second["steps_detail"][0]["added"]
    assert "tool:click" not in second["steps_detail"][0]["added"]


@pytest.mark.parametrize("output", ["null", '"truncated"', "incomplete JSON"])
def test_analysis_handles_unavailable_model_content(monkeypatch, output):
    span = _model_span([])
    span["attributes"].update({"input.value": "{}", "output.value": output})
    monkeypatch.setattr(analyze, "px_spans", lambda *_args: [span])

    result = analyze.analyze(_record("demo"), "test", None)

    assert result["steps"] == 1
    assert result["steps_detail"][0]["calls"] == []
    assert result["steps_detail"][0]["added"] == {}


async def test_finished_results_survive_an_interrupted_suite(tmp_path, monkeypatch):
    output = tmp_path / "run.json"
    benchmark = _benchmark([])

    async def execute(task, _options, _workspace, _attempt):
        if task.name == "second":
            raise asyncio.CancelledError
        return _record(task.name)

    monkeypatch.setattr(run, "run_task", execute)
    with pytest.raises(asyncio.CancelledError):
        await run.run_tasks(
            [_task("first"), _task("second")],
            runner.RunOptions("test"),
            benchmark,
            output,
            parallel=1,
        )

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert [record["task"] for record in saved["tasks"]] == ["first"]
    assert saved["tasks"][0]["status"] == "pass"


async def test_interruption_closes_other_attempts(tmp_path, monkeypatch):
    active = asyncio.Event()
    closed = asyncio.Event()

    async def execute(task, _options, _workspace, _attempt):
        if task.name == "first":
            await active.wait()
            raise asyncio.CancelledError
        active.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(run, "run_task", execute)
    with pytest.raises(asyncio.CancelledError):
        await run.run_tasks(
            [_task("first"), _task("second")],
            runner.RunOptions("test"),
            _benchmark([]),
            tmp_path / "run.json",
            parallel=2,
        )

    assert closed.is_set()


def test_failed_snapshot_write_preserves_previous_result(tmp_path, monkeypatch):
    output = tmp_path / "run.json"
    original = _benchmark([_record("first")])
    write_run(output, original)
    write_text = type(output).write_text

    def interrupted_write(path, *args, **kwargs):
        if path.suffix == ".tmp":
            write_text(path, "partial", encoding="utf-8")
            raise OSError("disk unavailable")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(type(output), "write_text", interrupted_write)
    with pytest.raises(OSError, match="disk unavailable"):
        write_run(output, _benchmark([_record("second")]))

    assert (
        BenchmarkResult.model_validate_json(output.read_text(encoding="utf-8"))
        == original
    )


def test_result_files_roundtrip_nested_pydantic_models(tmp_path):
    record = _record("demo")
    record.checks = [CheckResult(label="answer", ok=True, detail=None)]
    record.usage = Usage(input=10, output=2, cache_read=4, reasoning=1)
    original = _benchmark([record])
    output = tmp_path / "run.json"

    write_run(output, original)
    restored = BenchmarkResult.model_validate_json(output.read_text(encoding="utf-8"))

    assert restored == original
    assert restored.tasks[0].checks[0].ok is True
    assert restored.tasks[0].usage.input == 10
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["tasks"][0]["checks"][0]["detail"] is None
    assert "error" not in saved["tasks"][0]


@pytest.mark.parametrize("option", ["--repeat", "--parallel"])
@pytest.mark.parametrize("value", ["0", "-2"])
async def test_cli_rejects_nonpositive_counts(option, value, monkeypatch, capsys):
    monkeypatch.setattr(run, "load_dotenv", lambda: None)
    monkeypatch.setattr(sys, "argv", ["evals.run", option, value])

    with pytest.raises(SystemExit) as error:
        await run.main()

    assert error.value.code == 2
    assert "must be at least 1" in capsys.readouterr().err


def test_task_rejects_an_empty_step_budget():
    with pytest.raises(ValueError, match="max_steps must be at least 1"):
        Task("demo", "practice", "https://example.com", "Finish", (answer("done"),), 0)


def _task(name, checks=None):
    return Task(
        name, "practice", "https://example.com", "Finish", checks or (answer("done"),)
    )


def _record(name, status="pass", score=1.0):
    return TaskResult(
        task=name,
        stage="practice",
        tags=["forms"],
        attempt=1,
        url="https://example.com",
        workspace="unused",
        status=status,
        score=score,
        seconds=1.0,
        session_id=name,
    )


def _benchmark(records):
    return BenchmarkResult(
        run="test",
        model="test",
        selection="all",
        repeat=1,
        project="test",
        tasks=records,
    )


def _model_span(messages):
    return {
        "name": "harnessed.model",
        "start_time": "2026-11-09T12:00:00Z",
        "attributes": {"input.value": json.dumps(messages), "output.value": "{}"},
    }
