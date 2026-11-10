"""Shared JSON records and atomic persistence for benchmark results."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue


class AgentResponse(BaseModel):
    task_type: Literal["RETRIEVE", "MUTATE", "NAVIGATE"]
    status: Literal[
        "SUCCESS",
        "NOT_FOUND_ERROR",
        "ACTION_NOT_ALLOWED_ERROR",
        "PERMISSION_DENIED_ERROR",
        "DATA_VALIDATION_ERROR",
        "UNKNOWN_ERROR",
    ]
    retrieved_data: list[JsonValue] | None = None
    error_details: str | None = None


class ToolRecord(BaseModel):
    name: str
    # Older snapshots contain repr strings of Harnessed's immutable mappings.
    args: dict[str, JsonValue] | str
    error: bool
    chars: int
    preview: str


class CheckResult(BaseModel):
    label: str
    ok: bool
    detail: str | None
    error: str | None = None


class Usage(BaseModel):
    input: int
    output: int
    cache_read: int | None
    reasoning: int | None


class TaskResult(BaseModel):
    task: str
    task_id: int | None = None
    revision: int | None = None
    sites: list[str] = Field(default_factory=list)
    stage: str
    tags: list[str]
    attempt: int = Field(default=1, ge=1)
    url: str
    workspace: str
    status: Literal["pass", "fail", "error"]
    score: float
    seconds: float
    session_id: str | None = None
    completed: bool | None = None
    stop_reason: str | None = None
    answer: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    probes: dict[str, Any] = Field(default_factory=dict)
    usage: Usage | None = None
    tool_calls: int | None = None
    tool_errors: int | None = None
    tools: list[ToolRecord] = Field(default_factory=list)
    error: str | None = None
    error_phase: (
        Literal["setup", "execution", "evidence", "checks", "evaluation"] | None
    ) = None


class BenchmarkResult(BaseModel):
    run: str
    subset: str | None = None
    dataset_sha256: str | None = None
    upstream_revision: str | None = None
    upstream_version: str | None = None
    max_steps: int | None = None
    timeout: int | None = None
    model: str
    # Snapshots written before subscription support used API keys.
    provider: Literal["openai", "openai-codex"] = "openai"
    selection: str
    repeat: int = Field(ge=1)
    project: str
    tasks: list[TaskResult]


def write_run(path: Path, run: BenchmarkResult) -> None:
    """Replace the last snapshot only after the complete JSON was written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = run.model_dump_json(indent=2, exclude_unset=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
