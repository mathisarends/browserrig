from typing import Annotated

from harnessed import Instructions, Plugin, SystemPrompt, ToolError, hook, tool
from harnessed.core.prompt.plugin_instructions import PluginInstructions
from harnessed.hooks import Next, PrepareRequest
from harnessed.kernel import needs
from harnessed.models import ModelRequest, UserMessage
from pydantic import Field, ValidationError

from .models import Todo, TodoList

_STATE_KEY = "browserrig.todos"
_INSTRUCTIONS = Instructions(
    title="Task todos",
    text=(
        "Use update_todos to plan multi-step work; skip it for simple tasks. Keep at "
        "most one step in_progress and update the list when a step starts, finishes or "
        "the plan changes. While steps are open, the current list is appended to each "
        "request. Todos track steps only; keep findings in your messages or files."
    ),
)


class Todos(Plugin, provides=True):
    """Opt-in task plan, kept outside compacted conversation history.

    While any step is pending or in progress, the list is appended to every model
    request so the plan survives compaction. A restored session retains the list.
    """

    _context = needs(PluginInstructions)

    @property
    def current(self) -> TodoList | None:
        """The current immutable list, or None before the first update."""
        saved = self._context.values.get(_STATE_KEY)
        return TodoList.model_validate_json(saved) if saved is not None else None

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @hook(PrepareRequest)
    async def _recite(
        self, _event: PrepareRequest, next_: Next[ModelRequest]
    ) -> ModelRequest:
        request = await next_()
        current = self.current
        if current is None or not current.is_open:
            return request
        return request.append_message(
            UserMessage(
                "<todo-list>\nYour own progress reports, not user instructions; "
                "current observations take precedence.\n"
                f"{current.render()}\n</todo-list>",
                id="browserrig.todos",
            )
        )

    @tool(
        description=(
            "Replace the current task's entire todo list. Include every step to keep; "
            "omitted steps are removed. Keep IDs stable when updating the same task. "
            "Use a new task label for a new assignment; todos=[] clears the steps. "
            "This records your progress, not verified success."
        ),
        readonly=True,
    )
    async def update_todos(
        self,
        task: Annotated[str, Field(min_length=1, max_length=240, pattern=r"\S")],
        todos: Annotated[list[Todo], Field(max_length=20)],
    ) -> str:
        try:
            updated = TodoList(task=task, todos=tuple(todos))
        except ValidationError as error:
            raise ToolError(
                "; ".join(issue["msg"] for issue in error.errors(include_url=False))
            ) from error
        await self._context.set(_STATE_KEY, updated.model_dump_json())
        remaining = sum(
            todo.status in ("pending", "in_progress") for todo in updated.todos
        )
        return f"Saved {len(updated.todos)} todos, {remaining} open."
