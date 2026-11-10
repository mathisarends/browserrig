import pytest
from harnessed import Agent, SessionState, ToolStatus
from harnessed.events import CompactionAppliedEvent, ToolCallFinishedEvent
from harnessed.integrations.json import JsonSessionStore
from harnessed.plugins import Compaction
from harnessed.testing import ScriptedModel, call

from browserrig import Todo, TodoList, Todos, browser_plugins

_CHOOSE = {"id": "choose", "title": "Pick the best-rated shoe", "status": "in_progress"}
_BUY = {"id": "buy", "title": "Purchase and inspect confirmation"}


class _Summary:
    async def summarize(self, _messages, *, max_tokens):
        assert max_tokens > 0
        return "Earlier browser work summarized."


def _update(*todos, task="Buy shoes"):
    return call("update_todos", task=task, todos=list(todos))


def _recited(request) -> str | None:
    last = request.messages[-1]
    return last.text if last.id == "browserrig.todos" else None


async def test_opt_in_plugin_recites_open_list_without_changing_the_prompt():
    model = ScriptedModel(["Done"])
    await Agent(model=model).run("Simple question")
    assert not model.requests[0].tools
    assert not any(isinstance(plugin, Todos) for plugin in browser_plugins())

    model = ScriptedModel([_update(_CHOOSE, _BUY), "Done"])
    async with Agent(model=model, plugins=[Todos()]).session() as session:
        fixed_prompt = await session.prompt.render()
        await session.run("Buy shoes")
        assert await session.prompt.render() == fixed_prompt
    assert _recited(model.requests[0]) is None
    assert _recited(model.requests[1]) == (
        "<todo-list>\n"
        "Your own progress reports, not user instructions; "
        "current observations take precedence.\n"
        "Task: Buy shoes\n"
        "[>] choose: Pick the best-rated shoe\n"
        "[ ] buy: Purchase and inspect confirmation\n"
        "</todo-list>"
    )


async def test_closed_or_cleared_list_is_not_recited():
    done = {**_CHOOSE, "status": "completed"}
    cancelled = {**_BUY, "status": "cancelled"}
    model = ScriptedModel(
        [_update(done, cancelled), "Done", _update(task="Next"), "Done"]
    )
    async with Agent(model=model, plugins=[Todos()]).session() as session:
        await session.run("Buy shoes")
        await session.run("Next")
        current = session.scope[Todos].current
    assert all(_recited(request) is None for request in model.requests)
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
    assert "[>] choose" in (_recited(model.requests[-1]) or "")


async def test_list_survives_compaction_snapshot_restore_and_store_reopen(tmp_path):
    fire = iter([False, False, True, *[False] * 10])
    model = ScriptedModel(
        [
            _update(_CHOOSE, _BUY, task="Draft"),
            _update(
                {**_CHOOSE, "status": "completed"}, {**_BUY, "status": "in_progress"}
            ),
            "Done",
            "Continued",
        ]
    )
    agent = Agent(
        model=model,
        plugins=[
            Todos(),
            Compaction(
                trigger=lambda _state: next(fire),
                summarizer=_Summary(),
                keep_turns=0,
                keep_steps=1,
            ),
        ],
        store=JsonSessionStore(root=tmp_path),
    )
    async with agent.session(id="shopping") as session:
        result = await session.run("Buy shoes")
        saved = session.snapshot().to_json()
        current = session.scope[Todos].current
    assert any(isinstance(event, CompactionAppliedEvent) for event in result.events)

    def history(request) -> str:
        return "\n".join(message.text for message in request.messages[:-1])

    after_compaction = model.requests[2]
    assert "Saved 2 todos, 2 open." in history(model.requests[1])
    assert "Saved 2 todos, 2 open." not in history(after_compaction)
    assert "Earlier browser work summarized." in history(after_compaction)
    assert "[>] buy" in (_recited(after_compaction) or "")

    async with agent.session(state=SessionState.from_json(saved)) as session:
        assert session.scope[Todos].current == current
        await session.run("Continue checkout")
    assert "[>] buy" in (_recited(model.requests[-1]) or "")

    reopened = Agent(
        model=ScriptedModel([]),
        plugins=[Todos()],
        store=JsonSessionStore(root=tmp_path),
    )
    async with reopened.session(id="shopping") as session:
        assert session.scope[Todos].current == current
    async with reopened.session(id="unrelated") as session:
        assert session.scope[Todos].current is None
