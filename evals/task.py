"""Frozen upstream task definitions and model-visible task inputs."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .freeze import DATA, LOCAL_SUBSET, PILOT_SUBSET, REVISION, SUBSET, VERSION


class EvaluationSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    evaluator: str
    expected: dict[str, JsonValue]
    results_schema: dict[str, JsonValue] | None = None


class Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    task_id: int
    intent_template_id: int
    revision: int
    sites: tuple[str, ...]
    start_urls: tuple[str, ...] = Field(min_length=1)
    intent: str
    eval: tuple[EvaluationSpec, ...] = Field(min_length=1)

    @property
    def name(self) -> str:
        return str(self.task_id)

    @property
    def action(self) -> str:
        response = next(
            item for item in self.eval if item.evaluator == "AgentResponseEvaluator"
        )
        return str(response.expected["task_type"]).lower()

    @property
    def response_schema(self) -> dict[str, JsonValue] | None:
        return next(
            item.results_schema
            for item in self.eval
            if item.evaluator == "AgentResponseEvaluator"
        )


class Manifest(BaseModel):
    name: str
    upstream: str
    version: str
    revision: str
    seed: str
    selection: str
    quotas: dict[str, int]
    task_ids: tuple[int, ...]
    hard_task_ids: tuple[int, ...]
    source_sha256: str
    hard_source_sha256: str
    tasks_sha256: str
    replacements: dict[str, int] = Field(default_factory=dict)
    replacement_reason: str | None = None
    excluded_candidates: dict[str, str] = Field(default_factory=dict)


def load_tasks(data: Path = DATA) -> tuple[Manifest, list[Task]]:
    """Fail closed when the checked-in benchmark or its provenance changes."""
    manifest = Manifest.model_validate_json((data / "manifest.json").read_bytes())
    payload = (data / "tasks.json").read_bytes()
    if manifest.name not in {SUBSET, PILOT_SUBSET, LOCAL_SUBSET} or (
        manifest.version,
        manifest.revision,
    ) != (VERSION, REVISION):
        raise ValueError("Unexpected WebArena subset or upstream revision")
    if hashlib.sha256(payload).hexdigest() != manifest.tasks_sha256:
        raise ValueError("Frozen WebArena task checksum mismatch")
    tasks = [Task.model_validate(item) for item in json.loads(payload)]
    ids = tuple(task.task_id for task in tasks)
    if len(ids) != 48 or len(set(ids)) != 48 or ids != manifest.task_ids:
        raise ValueError(
            "The frozen subset must contain its 48 unique, ordered task IDs"
        )
    if not set(ids) <= set(manifest.hard_task_ids):
        raise ValueError(
            "The subset contains tasks outside upstream WebArena-Verified Hard"
        )
    return manifest, tasks


def select(tasks: list[Task], spec: str | None) -> list[Task]:
    """Select frozen task IDs or @site/@operation filters; never resample."""
    if not spec:
        return list(tasks)
    selected: set[int] = set()
    for token in (part.strip() for part in spec.split(",") if part.strip()):
        if token.startswith("@"):
            key = token[1:]
            matches = [task for task in tasks if key in (*task.sites, task.action)]
        else:
            matches = [task for task in tasks if str(task.task_id) == token]
        if not matches:
            raise ValueError(f"No frozen task matches {token!r}")
        selected.update(task.task_id for task in matches)
    if not selected:
        raise ValueError("Select at least one frozen task")
    return [task for task in tasks if task.task_id in selected]
