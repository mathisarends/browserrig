"""Validate the actual pinned grader without a browser, Docker or model calls."""

import json

import pytest

from evals.environments import Environments
from evals.evaluate import evaluate
from evals.task import load_tasks
from evals.upstream import PROJECT


@pytest.mark.parametrize(
    ("case", "status", "score"),
    [
        ("correct", "success", 1),
        ("wrong", "failure", 0),
        ("unfinished", "failure", 0),
        ("unperformed_mutation", "failure", 0),
    ],
)
async def test_official_evaluator_grades_recorded_evidence(
    tmp_path, case, status, score
):
    if not (PROJECT / ".venv").is_dir():
        pytest.skip(
            "Install the locked evaluator: uv sync --project evals/evaluator --locked"
        )
    _, tasks = load_tasks()
    task = (
        next(task for task in tasks if task.action == "mutate")
        if case == "unperformed_mutation"
        else tasks[0]
    )
    workspace = tmp_path / task.name
    workspace.mkdir()
    (workspace / "environment.json").write_text(
        json.dumps(Environments().evaluator_config()), encoding="utf-8"
    )
    # The only recorded action is a GET: claiming a mutation must not be sufficient.
    (workspace / "network.har").write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "test", "version": "1"},
                    "entries": [
                        {
                            "request": {
                                "url": "http://localhost:9999/",
                                "method": "GET",
                                "headers": [],
                            },
                            "response": {
                                "status": 200,
                                "headers": [],
                                "content": {"mimeType": "text/html", "text": "<html/>"},
                            },
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    response = dict(task.eval[0].expected)
    response["task_type"] = str(response["task_type"]).upper()
    if case == "wrong":
        response["retrieved_data"] = []
    (workspace / "agent_response.json").write_text(
        json.dumps(None if case == "unfinished" else response), encoding="utf-8"
    )
    grade = await evaluate(workspace)
    assert (grade.status, grade.score) == (status, score), grade
