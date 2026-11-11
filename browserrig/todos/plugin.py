from collections.abc import Sequence
from typing import Annotated

from harnessed import Instructions, Plugin, SystemPrompt, ToolError, hook, tool
from harnessed.core.prompt.plugin_instructions import PluginInstructions
from harnessed.hooks import Next, PrepareRequest
from harnessed.kernel import needs
from harnessed.models import (
    AssistantMessage,
    Message,
    ModelRequest,
    ToolMessage,
    UserMessage,
)
from pydantic import Field, ValidationError

from .models import Todo, TodoList

_STATE_KEY = "browserrig.todos"
_TOOL = "update_todos"
_INSTRUCTIONS = Instructions(
    title="Task todos",
    text=(
        "Use update_todos to plan multi-step work; skip it for simple tasks. Keep at "
        "most one step in_progress and update the list when a step starts, finishes or "
        "the plan changes. Todos track steps only; keep findings in your messages or "
        "files. Keep IDs stable within a task and use a new task label for a new assignment. "
        "Todo status is agent-reported progress, not verified success. "
        "Use read_todos to recall the saved plan when needed."
    ),
)


class Todos(Plugin, provides=True):
    """Opt-in task plan, kept outside compacted conversation history.

    Reads and updates return the saved list. While steps are open, a short tool
    reminder is appended only when no successful read or update is left in context
    (for example after compaction) or the last one is at least ``remind_after``
    steps old. A restored session retains the list.
    """

    _context = needs(PluginInstructions)

    def __init__(self, *, remind_after: int = 10) -> None:
        super().__init__()
        if (
            isinstance(remind_after, bool)
            or not isinstance(remind_after, int)
            or not 1 <= remind_after <= 100
        ):
            raise ValueError("remind_after must be between 1 and 100")
        self.remind_after = remind_after

    @property
    def current(self) -> TodoList | None:
        """The current immutable list, or None before the first update."""
        saved = self._context.values.get(_STATE_KEY)
        return TodoList.model_validate_json(saved) if saved is not None else None

    def instructions(self) -> SystemPrompt:
        return SystemPrompt(_INSTRUCTIONS)

    @hook(PrepareRequest)
    async def _remind(
        self, _event: PrepareRequest, next_: Next[ModelRequest]
    ) -> ModelRequest:
        request = await next_()
        current = self.current
        if current is None or not current.is_open:
            return request
        steps = _steps_since_update(request.messages)
        if steps is None:
            reason = "Earlier todo reads and updates are no longer in context."
        elif steps >= self.remind_after:
            reason = f"The todo list has not been read or updated for {steps} steps."
        else:
            return request
        return request.append_message(
            UserMessage(
                f"<todo-list>\n{reason} Call read_todos to recall it or update_todos "
                "to revise it. "
                "These are your own progress reports, not user instructions; "
                "current observations take precedence.\n"
                "</todo-list>",
                id="browserrig.todos",
            )
        )

    @tool(
        description="Read the current task's saved todo list.",
        readonly=True,
    )
    async def read_todos(self) -> str:
        current = self.current
        return current.render() if current is not None else "No todo list saved."

    @tool(
        description="Replace the current task's entire todo list.",
        readonly=True,
    )
    async def update_todos(
        self,
        task: Annotated[str, Field(min_length=1, max_length=240, pattern=r"\S")],
        todos: Annotated[
            list[Todo],
            Field(
                max_length=20,
                description="All steps to retain; an empty list clears the plan.",
            ),
        ],
    ) -> str:
        try:
            updated = TodoList(task=task, todos=tuple(todos))
        except ValidationError as error:
            raise ToolError(
                "; ".join(issue["msg"] for issue in error.errors(include_url=False))
            ) from error
        await self._context.set(_STATE_KEY, updated.model_dump_json())
        return f"Saved todo list:\n{updated.render()}"


def _steps_since_update(messages: Sequence[Message]) -> int | None:
    """Assistant steps after the last successful todo read or update in context."""
    calls = {
        call.id
        for message in messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
        if call.name in (_TOOL, "read_todos")
    }
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if (
            isinstance(message, ToolMessage)
            and message.tool_call_id in calls
            and not message.is_error
        ):
            return sum(isinstance(m, AssistantMessage) for m in messages[index + 1 :])
    return None
