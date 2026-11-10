"""Evaluate saved attempts using the unmodified, locked upstream evaluator."""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import upstream
from .freeze import VERSION
from .results import CheckResult


class Assertion(BaseModel):
    model_config = ConfigDict(extra="allow")

    assertion_name: str
    status: str
    assertion_msgs: list[str] | None = None
    error_msg: str | None = None


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="allow")

    evaluator_name: str
    status: str
    score: float
    assertions: list[Assertion] | None = None
    error_msg: str | None = None


class Grade(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: int
    status: str
    score: float
    webarena_verified_version: str
    webarena_verified_data_checksum: str
    evaluators_results: list[Evaluation] = []
    error_msg: str | None = None

    def checks(self) -> list[CheckResult]:
        checks = []
        for index, result in enumerate(self.evaluators_results, 1):
            detail = result.error_msg or "; ".join(
                message
                for assertion in (result.assertions or [])
                if assertion.status != "success"
                for message in (
                    assertion.assertion_msgs
                    or [assertion.error_msg or assertion.assertion_name]
                )
            )
            checks.append(
                CheckResult(
                    label=f"{result.evaluator_name}:{index}",
                    ok=result.status == "success",
                    detail=detail or None,
                    error=detail if result.status == "error" else None,
                )
            )
        return checks


async def evaluate(workspace: Path) -> Grade:
    """No live browser, website, model or LLM judge is needed to re-grade a run."""
    task_id = int(workspace.name)
    output = workspace / "eval_result.json"
    output.unlink(missing_ok=True)
    await upstream.invoke(
        "eval-tasks",
        "--task-ids",
        str(task_id),
        "--output-dir",
        str(workspace.parent),
        "--config",
        str(workspace / "environment.json"),
        log=workspace / "evaluator.log",
        timeout=60,
        check=False,
    )
    if not output.exists():
        raise RuntimeError(
            f"Upstream produced no result; see {workspace / 'evaluator.log'}"
        )
    grade = Grade.model_validate_json(output.read_bytes())
    if grade.task_id != task_id or grade.webarena_verified_version != VERSION:
        raise ValueError("Unexpected evaluator version or task ID in upstream result")
    from .task import load_tasks  # pylint: disable=import-outside-toplevel

    manifest, _ = load_tasks()
    if grade.webarena_verified_data_checksum != manifest.source_sha256:
        raise ValueError("Evaluator did not grade the frozen dataset")
    return grade


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workspace", type=Path, help="Attempt directory ending in its numeric task ID"
    )
    args = parser.parse_args()
    result = await evaluate(args.workspace.resolve())
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
