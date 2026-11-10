"""Report coverage and evidence must not fabricate agent failures or successes."""

import json
import re
from collections import Counter

import pytest

from evals import analyze
from evals.html_report import build
from evals.network_evidence import differences, requests
from evals.results import BenchmarkResult, TaskResult, ToolRecord, Usage, write_run
from evals.task import load_tasks


def test_report_preserves_all_48_tasks_and_distinguishes_blocked_from_pending(tmp_path):
    path = tmp_path / "run.json"
    write_run(path, _run([_record(29)]))
    output = tmp_path / "report.html"

    report = build([path], output, {267: "disk space"}, "revision")

    assert Counter(task.status for task in report.tasks) == {
        "pass": 1,
        "blocked": 1,
        "pending": 46,
    }
    assert len(report.tasks) == 48
    assert next(task for task in report.tasks if task.task_id == 267).record is None
    assert (
        next(task for task in report.tasks if task.task_id == 106).input_tokens is None
    )
    assert output.is_file()


def test_report_rejects_duplicate_attempts_instead_of_picking_the_best(tmp_path):
    paths = [tmp_path / "one.json", tmp_path / "two.json"]
    write_run(paths[0], _run([_record(29)]))
    write_run(paths[1], _run([_record(29, "fail")]))

    with pytest.raises(ValueError, match="Duplicate task 29"):
        build(paths, tmp_path / "report.html", {}, "revision")


def test_report_rejects_incompatible_budgets(tmp_path):
    paths = [tmp_path / "one.json", tmp_path / "two.json"]
    write_run(paths[0], _run([]))
    other = _run([])
    other.max_steps = 100
    write_run(paths[1], other)

    with pytest.raises(
        ValueError, match="different datasets, models, providers or budgets"
    ):
        build(paths, tmp_path / "report.html", {}, "revision")


def test_partial_trace_keeps_complete_local_tool_records(tmp_path, monkeypatch):
    record = _record(29)
    record.session_id = "session"
    record.usage = Usage(input=10, output=2, cache_read=0, reasoning=0)
    record.tools = [
        ToolRecord(name=name, args={}, error=False, chars=4, preview="done")
        for name in ("click", "type_text")
    ]
    record.tool_calls = 2
    path = tmp_path / "run.json"
    write_run(path, _run([record]))
    spans = [
        {
            "name": "harnessed.model",
            "start_time": "2026-11-10T00:00:00Z",
            "context": {"trace_id": "trace"},
            "attributes": {
                "llm.token_count.prompt": 5,
                "input.value": "[]",
                "output.value": "{}",
            },
        },
        {
            "name": "harnessed.tool",
            "start_time": "2026-11-10T00:00:01Z",
            "attributes": {
                "tool.name": "click",
                "input.value": "{}",
                "output.value": "done",
            },
        },
    ]
    monkeypatch.setattr(analyze, "px_spans", lambda *_args: spans)

    report = build([path], tmp_path / "report.html", {}, "revision")

    assert report.tasks[0].metrics["trace_coverage"] == "partial"
    assert "5/10" in report.tasks[0].trace_error
    assert [tool.name for tool in report.tasks[0].tools] == ["click", "type_text"]
    assert report.tasks[0].input_tokens == 10


def test_setup_archive_cannot_hide_an_actual_agent_attempt(tmp_path):
    record = _record(29)
    record.session_id = "agent-was-started"
    write_run(tmp_path / "setup-only-test-suite-archive.json", _run([record]))
    path = tmp_path / "run.json"
    write_run(path, _run([]))

    with pytest.raises(ValueError, match="setup-only run contains agent execution"):
        build([path], tmp_path / "report.html", {}, "revision")


def test_report_embeds_untrusted_tool_text_as_json_without_script_injection(tmp_path):
    record = _record(29, "error")
    record.error = '</script><script>alert("injected")</script>'
    path = tmp_path / "run.json"
    write_run(path, _run([record]))
    output = tmp_path / "report.html"

    build([path], output, {}, "revision")

    html = output.read_text("utf-8")
    assert record.error not in html
    payload = re.search(r'id="report-data">(.*?)</script>', html, re.S).group(1)
    data = json.loads(payload)
    assert data["tasks"][0]["record"]["error"] == record.error


@pytest.mark.parametrize("review_session", ["current", "older"])
def test_trace_reviews_only_apply_to_the_reviewed_session(
    tmp_path, monkeypatch, review_session
):
    record = _record(29)
    record.session_id = "current"
    path = tmp_path / "run.json"
    write_run(path, _run([record]))
    output = tmp_path / "report.html"
    output.with_suffix(".reviews.json").write_text(
        json.dumps(
            {
                "29": [
                    {
                        "category": "review-test",
                        "title": "Reviewed finding",
                        "confidence": "Hypothese",
                        "evidence": ["recorded evidence"],
                        "fix": "test a fix",
                        "source": "Trace-Review",
                        "session_id": review_session,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(analyze, "px_spans", lambda *_args: [])

    report = build([path], output, {}, "revision")

    reviews = [
        finding
        for finding in report.tasks[0].findings
        if finding.source == "Trace-Review"
    ]
    assert bool(reviews) == (review_session == "current")


def test_multipart_evidence_redacts_tokens_and_exposes_wrong_destination(tmp_path):
    (tmp_path / "environment.json").write_text(
        json.dumps(
            {
                "environments": {"__REDDIT__": {"urls": ["http://localhost:9999"]}},
            }
        ),
        encoding="utf-8",
    )
    body = "\r\n".join(
        [
            "--boundary",
            'Content-Disposition: form-data; name="submission[forum]"',
            "",
            "wrong-forum",
            "--boundary",
            'Content-Disposition: form-data; name="submission[_token]"',
            "",
            "secret-csrf",
            "--boundary--",
            "",
        ]
    )
    (tmp_path / "network.har").write_text(
        json.dumps(
            {
                "log": {
                    "entries": [
                        {
                            "request": {
                                "method": "POST",
                                "url": "http://localhost:9999/submit/technology",
                                "postData": {
                                    "mimeType": "multipart/form-data; boundary=boundary",
                                    "text": body,
                                },
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    recorded = requests(tmp_path)
    grade = {
        "evaluators_results": [
            {
                "evaluator_name": "NetworkEventEvaluator",
                "status": "failure",
                "actual": [],
                "expected": {"post_data": {"submission[forum]": "correct-forum"}},
            }
        ]
    }

    diff = differences(grade, recorded)

    assert recorded[0].fields["submission[_token]"] == "[redacted]"
    assert len(diff) == 1
    assert (diff[0].field, diff[0].expected, diff[0].actual) == (
        "submission[forum]",
        "correct-forum",
        "wrong-forum",
    )


def _record(task_id, status="pass"):
    return TaskResult(
        task=str(task_id),
        task_id=task_id,
        stage="webarena-verified-hard",
        tags=[],
        url="http://localhost:9999",
        workspace="nonexistent-test-workspace",
        status=status,
        score=int(status == "pass"),
        seconds=1,
    )


def _run(records):
    manifest, _ = load_tasks()
    return BenchmarkResult(
        run="test",
        subset=manifest.name,
        dataset_sha256=manifest.tasks_sha256,
        model="test",
        provider="openai-codex",
        selection="test",
        repeat=1,
        project="test",
        max_steps=50,
        timeout=300,
        tasks=records,
    )
