"""Offline regression checks for frozen tasks, official grading and trace analysis."""

import asyncio
import json
import sys
from collections import Counter
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from harnessed import ToolCall, ToolResult
from harnessed.events import ToolCallFinishedEvent

from evals import analyze, evaluate, report, run, runner
from evals.environments import Environments
from evals.evaluate import Grade
from evals.freeze import DATA, QUOTAS, SUBSET, VERSION
from evals.results import (
    AgentResponse,
    BenchmarkResult,
    CheckResult,
    TaskResult,
    Usage,
    write_run,
)
from evals.task import load_tasks, select


@pytest.fixture(name="agent_result")
def prepared_agent_result(monkeypatch):
    manifest, _ = load_tasks()
    grade = Grade(
        task_id=29,
        status="success",
        score=1,
        webarena_verified_version=VERSION,
        webarena_verified_data_checksum=manifest.source_sha256,
    )
    result = SimpleNamespace(
        text="done",
        output=AgentResponse(
            task_type="RETRIEVE", status="SUCCESS", retrieved_data=["answer"]
        ),
        completed=True,
        stop_reason="completed",
        events=[],
        messages=[],
        grade=grade,
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=2, cache_read_tokens=4, reasoning_tokens=1
        ),
    )

    async def execute(*_args, **_kwargs):
        return result

    async def reset(*_args):
        return None

    async def grading(workspace):
        assert (workspace / "network.har").exists(), "HAR must flush before grading"
        return result.grade

    @asynccontextmanager
    async def recording(_task, _env, workspace, **_kwargs):
        try:
            yield "http://localhost:9222", "target"
        finally:
            (workspace / "network.har").write_text("{}", encoding="utf-8")

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(id="session", run=execute)

    monkeypatch.setattr(
        runner, "_agent", lambda *_args: SimpleNamespace(session=session)
    )
    monkeypatch.setattr(runner, "recording_browser", recording)
    monkeypatch.setattr(runner, "evaluate", grading)
    monkeypatch.setattr(Environments, "reset", reset)
    return result


def test_frozen_subset_has_the_exact_hard_membership_and_coverage():
    manifest, tasks = load_tasks()
    assert manifest.name == SUBSET
    assert len(tasks) == len({task.task_id for task in tasks}) == 48
    assert {task.task_id for task in tasks} <= set(manifest.hard_task_ids)
    assert Counter("+".join(sorted(task.sites)) for task in tasks) == QUOTAS
    assert Counter(task.action for task in tasks) == {
        "mutate": 29,
        "retrieve": 13,
        "navigate": 6,
    }


def test_tampered_dataset_is_rejected(tmp_path):
    (tmp_path / "manifest.json").write_bytes((DATA / "manifest.json").read_bytes())
    (tmp_path / "tasks.json").write_bytes((DATA / "tasks.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_tasks(tmp_path)


def test_selection_never_resamples_and_rejects_unknown_ids():
    _, tasks = load_tasks()
    assert [task.task_id for task in select(tasks, "106,29,29")] == [29, 106]
    assert all(task.action == "navigate" for task in select(tasks, "@navigate"))
    with pytest.raises(ValueError, match="No frozen task"):
        select(tasks, "9999")


def test_cross_site_setup_isolates_port_independent_php_session_cookies():
    original = Environments()

    isolated = original.for_task(("shopping", "reddit"))

    assert isolated.sites["shopping"].url == "http://shopping.localhost:7770"
    assert isolated.sites["reddit"].url == "http://reddit.localhost:9999"
    assert original.sites["shopping"].url == "http://localhost:7770"
    assert isolated.evaluator_config()["environments"]["__SHOPPING__"]["urls"] == [
        "http://shopping.localhost:7770"
    ]


def test_agent_prompt_does_not_include_grading_rules_or_reference_answers():
    task = _task().model_copy(
        update={
            "intent": "Do a test.",
            "eval": (
                _task()
                .eval[0]
                .model_copy(
                    update={
                        "expected": {
                            "task_type": "retrieve",
                            "retrieved_data": ["SECRET_REFERENCE_ANSWER"],
                        }
                    }
                ),
            ),
        }
    )
    prompt = runner.task_prompt(task, Environments())
    assert "Do a test." in prompt
    assert "SECRET_REFERENCE_ANSWER" not in prompt
    assert "expected" not in prompt
    assert "AgentResponseEvaluator" not in prompt


@pytest.mark.parametrize(
    ("completed", "status", "score"), [(True, "pass", 1), (False, "fail", 0)]
)
async def test_unfinished_agent_cannot_pass(
    tmp_path, agent_result, completed, status, score
):
    agent_result.completed = completed
    result = await runner.run_task(_task(), runner.RunOptions("test"), tmp_path / "29")
    assert result.status == status, result.error
    assert result.score == score
    assert result.usage.input == 10
    saved = json.loads((tmp_path / "29/agent_response.json").read_text("utf-8"))
    assert (saved is not None) == completed


async def test_evaluator_errors_preserve_execution_evidence(tmp_path, agent_result):
    agent_result.grade.status = "error"
    agent_result.grade.error_msg = "broken evaluator"
    result = await runner.run_task(_task(), runner.RunOptions("test"), tmp_path / "29")
    assert result.status == "error"
    assert result.error_phase == "evaluation"
    assert result.error == "broken evaluator"
    assert result.answer and result.usage.output == 2


async def test_tool_evidence_serializes_harnessed_arguments(tmp_path, agent_result):
    agent_result.events = [
        ToolCallFinishedEvent(
            call=ToolCall(
                "upload_files", {"paths": ["note.txt"], "options": {"mode": "test"}}
            ),
            result=ToolResult("uploaded"),
        )
    ]
    result = await runner.run_task(_task(), runner.RunOptions("test"), tmp_path / "29")
    assert result.status == "pass", result.error
    assert result.tool_calls == 1
    assert result.tools[0].args == {"paths": ["note.txt"], "options": {"mode": "test"}}


async def test_workspace_setup_failure_becomes_a_task_error(tmp_path):
    workspace = tmp_path / "file"
    workspace.write_text("occupied", encoding="utf-8")
    result = await runner.run_task(_task(), runner.RunOptions("test"), workspace)
    assert result.status == "error"
    assert result.error_phase == "setup"
    assert "FileExistsError" in result.error


@pytest.mark.usefixtures("agent_result")
async def test_run_cancellation_propagates_and_flushes_har(tmp_path, monkeypatch):
    def cancel(*_args):
        raise asyncio.CancelledError

    monkeypatch.setattr(runner, "_agent", cancel)
    with pytest.raises(asyncio.CancelledError):
        await runner.run_task(_task(), runner.RunOptions("test"), tmp_path / "29")
    assert (tmp_path / "29/network.har").exists()


@pytest.mark.usefixtures("agent_result")
async def test_timeout_is_an_agent_failure(tmp_path, monkeypatch):
    async def timeout(*_args, **_kwargs):
        raise TimeoutError

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(id="session", run=timeout)

    monkeypatch.setattr(
        runner, "_agent", lambda *_args: SimpleNamespace(session=session)
    )
    result = await runner.run_task(_task(), runner.RunOptions("test"), tmp_path / "29")
    assert result.status == "fail", result.error
    assert result.score == 0
    assert result.stop_reason == "timeout"


@pytest.mark.parametrize("checksum_matches", [True, False])
async def test_official_result_parsing_and_dataset_validation(
    tmp_path, monkeypatch, checksum_matches
):
    manifest, _ = load_tasks()
    workspace = tmp_path / "29"
    workspace.mkdir()

    async def invoke(*_args, **_kwargs):
        (workspace / "eval_result.json").write_text(
            json.dumps(
                {
                    "task_id": 29,
                    "status": "success",
                    "score": 1,
                    "webarena_verified_version": VERSION,
                    "webarena_verified_data_checksum": manifest.source_sha256
                    if checksum_matches
                    else "wrong",
                    "evaluators_results": [
                        {
                            "evaluator_name": "AgentResponseEvaluator",
                            "status": "success",
                            "score": 1,
                            "assertions": None,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(evaluate.upstream, "invoke", invoke)
    if not checksum_matches:
        with pytest.raises(ValueError, match="frozen dataset"):
            await evaluate.evaluate(workspace)
    else:
        grade = await evaluate.evaluate(workspace)
        assert grade.checks()[0].ok


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

    async def execute(task, _options, _workspace, _attempt, _environments):
        if task.task_id == 106:
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
    assert [record["task"] for record in saved["tasks"]] == ["29"]
    assert saved["tasks"][0]["status"] == "pass"


async def test_shared_sites_reject_parallel_execution(tmp_path):
    with pytest.raises(ValueError, match="parallel must be 1"):
        await run.run_tasks(
            [],
            runner.RunOptions("test"),
            _benchmark([]),
            tmp_path / "run.json",
            parallel=2,
        )


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


@pytest.fixture(name="benchmark_cli")
def prepared_benchmark_cli(tmp_path, monkeypatch):
    pytest.importorskip("pydantic_ai.models.openai_codex")
    captured = {}

    async def execute(_tasks, options, benchmark, output, _parallel, **_kwargs):
        captured.update(options=options, benchmark=benchmark, output=output)

    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "test-access",
                    "refresh_token": "test-refresh",
                    "account_id": "test-account",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-astra")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(run, "load_dotenv", lambda: None)
    monkeypatch.setattr(run, "run_tasks", execute)

    async def preflight(*_args):
        return None

    monkeypatch.setattr(run, "preflight", preflight)
    monkeypatch.setattr(report, "RESULTS", tmp_path / "results")
    return captured


@pytest.mark.parametrize("api_key", [None, "test-api-key"])
async def test_cli_defaults_to_subscription_and_terra(
    benchmark_cli, monkeypatch, api_key
):
    if api_key is not None:
        monkeypatch.setenv("OPENAI_API_KEY", api_key)
    monkeypatch.setattr(sys, "argv", ["evals.run", "--tasks", "29"])

    await run.main()

    native = benchmark_cli["options"].model
    assert native.system == "openai-codex"
    assert native.model_name == "gpt-6.1-terra"
    saved = json.loads(benchmark_cli["output"].read_text(encoding="utf-8"))
    assert saved["provider"] == "openai-codex"
    assert saved["model"] == "gpt-6.1-terra"
    assert saved["context_window"] == 256_000
    assert saved["reserve_tokens"] == 8192
    assert saved["keep_last_steps"] == 2
    assert saved["target_ratio"] == 0.4
    assert saved["max_summary_tokens"] == 8192


@pytest.mark.parametrize(
    ("provider", "model_args", "expected_model"),
    [
        ("openai-codex", ["--model", "gpt-6-luna"], "gpt-6-luna"),
        ("openai", [], "gpt-6-astra"),
        ("openai", ["--model", "gpt-6.1-terra"], "gpt-6.1-terra"),
    ],
)
async def test_cli_explicit_provider_and_model(
    benchmark_cli, monkeypatch, provider, model_args, expected_model
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evals.run",
            "--tasks",
            "29",
            "--provider",
            provider,
            *model_args,
        ],
    )

    await run.main()

    native = benchmark_cli["options"].model
    assert native.system == provider
    assert native.model_name == expected_model
    assert benchmark_cli["benchmark"].provider == provider


async def test_cli_missing_subscription_login_does_not_fall_back_to_api(
    benchmark_cli, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(sys, "argv", ["evals.run", "--tasks", "29"])

    with pytest.raises(SystemExit) as error:
        await run.main()

    assert error.value.code == 2
    assert "codex login" in capsys.readouterr().err
    assert not benchmark_cli
    assert not (tmp_path / "results").exists()


async def test_cli_api_provider_requires_key(benchmark_cli, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evals.run", "--provider", "openai"])

    with pytest.raises(SystemExit) as error:
        await run.main()

    assert error.value.code == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert not benchmark_cli


async def test_cli_lists_tasks_without_credentials(
    benchmark_cli, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    monkeypatch.setattr(sys, "argv", ["evals.run", "--list"])

    await run.main()

    assert "48 tasks" in capsys.readouterr().out
    assert not benchmark_cli


def test_legacy_results_default_to_api_provider():
    payload = _benchmark([]).model_dump(exclude_unset=True)
    assert "provider" not in payload

    restored = BenchmarkResult.model_validate(payload)

    assert restored.provider == "openai"


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
    with pytest.raises(ValueError, match="budgets must be at least 1"):
        runner.RunOptions("test", max_steps=0)


def _task(name="demo"):
    _, tasks = load_tasks()
    return tasks[1] if name == "second" else tasks[0]


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
