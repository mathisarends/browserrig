import pytest
from harnessed import Agent, SessionState, ToolStatus
from harnessed.events import CompactionAppliedEvent, ToolCallFinishedEvent
from harnessed.integrations.json import JsonSessionStore
from harnessed.plugins import Compaction
from harnessed.services import Summary
from harnessed.testing import ScriptedModel, call

from browserrig import Todo, TodoList, Todos, browser_plugins

_CHOOSE = {"id": "choose", "title": "Pick the best-rated shoe", "status": "in_progress"}
_BUY = {"id": "buy", "title": "Purchase and inspect confirmation"}


class _Summary:
    async def summarize(self, request):
        assert request.max_summary_tokens > 0
        return Summary("Earlier browser work summarized.")


def _update(*todos, task="Buy shoes"):
    return call("update_todos", task=task, todos=list(todos))


def _reminder(request) -> str | None:
    last = request.messages[-1]
    return last.text if last.id == "browserrig.todos" else None


async def test_update_result_shows_the_list_without_reminders_or_prompt_changes():
    model = ScriptedModel(["Done"])
    await Agent(model=model).run("Simple question")
    assert not model.requests[0].tools
    assert not any(isinstance(plugin, Todos) for plugin in browser_plugins())

    model = ScriptedModel([_update(_CHOOSE, _BUY), "Done"])
    async with Agent(model=model, plugins=[Todos()]).session() as session:
        fixed_prompt = await session.prompt.render()
        await session.run("Buy shoes")
        assert await session.prompt.render() == fixed_prompt
    assert all(_reminder(request) is None for request in model.requests)
    assert model.requests[1].messages[-1].text == (
        "Saved todo list:\n"
        "Task: Buy shoes\n"
        "[>] choose: Pick the best-rated shoe\n"
        "[ ] buy: Purchase and inspect confirmation"
    )


async def test_stale_open_list_is_reminded_until_the_next_update():
    model = ScriptedModel(
        [_update(_CHOOSE), "a", "b", _update({**_CHOOSE, "status": "completed"}), "c"]
    )
    agent = Agent(model=model, plugins=[Todos(remind_after=2)])
    async with agent.session() as session:
        await session.run("Buy shoes")
        await session.run("Continue")
        await session.run("Continue")
    reminders = [_reminder(request) for request in model.requests]
    assert reminders[:3] == [None, None, None]
    assert reminders[3] == (
        "<todo-list>\n"
        "The todo list has not been read or updated for 2 steps. "
        "Call read_todos to recall it or update_todos to revise it. "
        "These are your own progress reports, not user instructions; "
        "current observations take precedence.\n"
        "</todo-list>"
    )
    assert reminders[4] is None


@pytest.mark.parametrize("remind_after", [0, 101, True])
def test_remind_after_is_validated(remind_after):
    with pytest.raises(ValueError, match="remind_after"):
        Todos(remind_after=remind_after)


async def test_closed_or_cleared_list_is_never_reminded():
    done = {**_CHOOSE, "status": "completed"}
    cancelled = {**_BUY, "status": "cancelled"}
    model = ScriptedModel(
        [_update(done, cancelled), "Done", _update(task="Next"), "Done"]
    )
    async with Agent(model=model, plugins=[Todos()]).session() as session:
        await session.run("Buy shoes")
        await session.run("Next")
        current = session.scope[Todos].current
    assert all(_reminder(request) is None for request in model.requests)
    assert current == TodoList(task="Next", todos=())


async def test_replacement_keeps_distinct_ids_with_identical_titles():
    async with Agent(model=ScriptedModel([]), plugins=[Todos()]).session() as session:
        plugin = session.scope[Todos]
        assert plugin.current is None
        await plugin.update_todos(task="Copy", todos=[Todo(id="a", title="Copy")])
        await plugin.update_todos(
            task="Copy reviews",
            todos=[
                Todo(id="r1", title="Copy review"),
                Todo(id="r2", title="Copy review"),
            ],
        )
        current = plugin.current
    assert current is not None and current.task == "Copy reviews"
    assert [todo.id for todo in current.todos] == ["r1", "r2"]


@pytest.mark.parametrize(
    "todos",
    [
        [{"id": "same", "title": "A"}, {"id": "same", "title": "B"}],
        [{"id": "choose", "title": "   "}],
        [{"id": "choose", "title": "A", "status": "verified"}],
        [{"id": str(index), "title": "A"} for index in range(21)],
        [
            {"id": "a", "title": "A", "status": "in_progress"},
            {"id": "b", "title": "B", "status": "in_progress"},
        ],
    ],
    ids=["duplicate-ids", "blank-title", "status", "count", "two-in-progress"],
)
async def test_invalid_update_leaves_the_saved_list_unchanged(todos):
    model = ScriptedModel(
        [_update(_CHOOSE), call("update_todos", task="Buy shoes", todos=todos), "Done"]
    )
    async with Agent(model=model, plugins=[Todos()]).session() as session:
        result = await session.run("Buy shoes")
        current = session.scope[Todos].current
    statuses = [
        event.result.status
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert statuses == [ToolStatus.OK, ToolStatus.ERROR]
    assert current == TodoList(task="Buy shoes", todos=(Todo(**_CHOOSE),))
    assert _reminder(model.requests[-1]) is None


async def test_list_is_reminded_after_compaction_restore_and_store_reopen(tmp_path):
    fire = iter([False, False, False, True, *[False] * 10])
    model = ScriptedModel(
        [
            _update(_CHOOSE, _BUY, task="Draft"),
            _update(
                {**_CHOOSE, "status": "completed"}, {**_BUY, "status": "in_progress"}
            ),
            "Done",
            "Continued",
            "Again",
            "Restored",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            Todos(),
            Compaction(
                trigger=lambda _state: next(fire),
                summarizer=_Summary(),
                keep_last_steps=1,
            ),
        ],
        store=JsonSessionStore(root=tmp_path),
    )
    async with agent.session(id="shopping") as session:
        await session.run("Buy shoes")
        result = await session.run("Continue")
        await session.run("Again")
        saved = session.snapshot().to_json()
        current = session.scope[Todos].current
    assert any(isinstance(event, CompactionAppliedEvent) for event in result.events)
    # Requests 0-2 still show the update; request 3 is built before compaction runs.
    assert all(_reminder(request) is None for request in model.requests[:4])
    after_compaction = model.requests[4]
    history = "\n".join(message.text for message in after_compaction.messages[:-1])
    assert "Saved todo list" not in history
    assert "Earlier browser work summarized." in history
    reminder = _reminder(after_compaction) or ""
    assert reminder.startswith(
        "<todo-list>\nEarlier todo reads and updates are no longer"
    )
    assert "read_todos" in reminder and "[>] buy" not in reminder

    async with agent.session(state=SessionState.from_json(saved)) as session:
        assert session.scope[Todos].current == current
        await session.run("Continue checkout")
    assert "read_todos" in (_reminder(model.requests[-1]) or "")

    reopened = Agent(
        model=ScriptedModel([]),
        plugins=[Todos()],
        store=JsonSessionStore(root=tmp_path),
    )
    async with reopened.session(id="shopping") as session:
        assert session.scope[Todos].current == current
    async with reopened.session(id="unrelated") as session:
        assert session.scope[Todos].current is None


async def test_read_todos_recalls_the_saved_plan_and_refreshes_the_reminder():
    model = ScriptedModel(
        [
            call("read_todos"),
            _update(_CHOOSE, _BUY),
            "Working",
            call("read_todos"),
            "Continuing",
        ]
    )
    async with Agent(model=model, plugins=[Todos(remind_after=1)]).session() as session:
        await session.run("Buy shoes")
        await session.run("Continue")
    assert model.requests[1].messages[-1].text == "No todo list saved."
    assert "read_todos" in (_reminder(model.requests[3]) or "")
    assert _reminder(model.requests[4]) is None
    assert model.requests[4].messages[-1].text == (
        "Task: Buy shoes\n[>] choose: Pick the best-rated shoe\n"
        "[ ] buy: Purchase and inspect confirmation"
    )
