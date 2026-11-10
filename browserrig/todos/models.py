from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from browserrig.core import Options

TodoStatus = Literal["pending", "in_progress", "completed", "cancelled"]

_MARKERS: dict[TodoStatus, str] = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
    "cancelled": "[-]",
}


class Todo(Options):
    """One agent-reported step; completion is not verified."""

    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,63}$")
    title: Annotated[str, Field(min_length=1, max_length=240, pattern=r"\S")]
    status: TodoStatus = "pending"


class TodoList(Options):
    """A bounded, immutable snapshot of the current task's plan."""

    task: Annotated[str, Field(min_length=1, max_length=240, pattern=r"\S")]
    todos: tuple[Todo, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def _validate_list(self) -> Self:
        if len({todo.id for todo in self.todos}) != len(self.todos):
            raise ValueError("Todo IDs must be unique within the list")
        if sum(todo.status == "in_progress" for todo in self.todos) > 1:
            raise ValueError("At most one todo may be in_progress")
        return self

    @property
    def is_open(self) -> bool:
        """Whether any step is still pending or in progress."""
        return any(todo.status in ("pending", "in_progress") for todo in self.todos)

    def render(self) -> str:
        """Compact text form shown to the model while steps are open."""
        lines = [f"Task: {self.task}"]
        lines += [f"{_MARKERS[t.status]} {t.id}: {t.title}" for t in self.todos]
        return "\n".join(lines)
