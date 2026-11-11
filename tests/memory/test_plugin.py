import hashlib

import pytest
from harnessed import Agent, PolicyDecision, SessionState
from harnessed.events import CompactionAppliedEvent
from harnessed.integrations.json import JsonSessionStore
from harnessed.models import (
    AssistantMessage,
    ModelInfo,
    ModelResponse,
    ModelUsage,
    StopReason,
)
from harnessed.plugins import Approvals
from harnessed.services import Summary
from harnessed.testing import ScriptedModel, call

from browserrig import (
    Files,
    LocalWorkspace,
    MemoryAction,
    TaskMemory,
    TaskMemoryEvent,
    WorkspaceTools,
)

_PATH = "notes/task_state.md"
_NOTES = "Requirements: 5 reviews. Best candidate B, source /products/2. Not purchased."


class _Summary:
    def __init__(self):
        self.budgets = []

    async def summarize(self, request):
        self.budgets.append(request.max_summary_tokens)
        return Summary("Earlier work: candidates examined, purchase still unconfirmed.")


def _plugins(tmp_path, memory):
    return [
        Files(LocalWorkspace(tmp_path)),
        WorkspaceTools(),
        memory,
        Approvals(default=PolicyDecision.ALLOW),
    ]


def _save(content=_NOTES):
    return call("write_file", path=_PATH, content=content, overwrite=True)


async def test_checkpoint_defers_once_then_first_compacted_request_prompts_a_read(
    tmp_path,
):
    summary = _Summary()
    model = ScriptedModel(
        [
            call("write_file", path="scratch.txt", content="old " * 2000),
            call("write_file", path="more.txt", content="more " * 4000),
            _save(),
            call("read_file", path=_PATH),
            "Finished",
        ],
        info=ModelInfo("test"),
    )
    memory = TaskMemory(
        trigger=lambda state: state.input_tokens >= 5000,
        fallback_tokens=5000,
        summarizer=summary,
        keep_last_steps=1,
        max_summary_tokens=2048,
    )
    async with Agent(
        model=model, plugins=_plugins(tmp_path, memory)
    ).session() as session:
        result = await session.run("Compare products", max_steps=8)
        state = session.scope[TaskMemory].current
    applied = [e for e in result.events if isinstance(e, CompactionAppliedEvent)]
    assert len(applied) == len(summary.budgets) == 1
    # Compaction is due at request 2, but the agent first gets a normal save step.
    assert "Context compaction is approaching" in model.requests[2].messages[-1].text
    assert not any(
        "Task memory handover:" in m.text for m in model.requests[2].messages
    )
    first_compacted = model.requests[3]
    assert any(
        f'read_file(path="{_PATH}")' in m.text and "Task memory handover:" in m.text
        for m in first_compacted.messages
    )
    assert (tmp_path / _PATH).read_text() == _NOTES
    assert state.revision == hashlib.sha256(_NOTES.encode()).hexdigest()
    assert state.restore_pending is False
    events = [e for e in result.events if isinstance(e, TaskMemoryEvent)]
    handover = next(e for e in events if e.action is MemoryAction.COMPACTED)
    assert handover.checkpoint_saved and handover.revision == state.revision
    restored = next(e for e in events if e.action is MemoryAction.RESTORED)
    assert restored.compaction_id == handover.compaction_id == applied[0].id
    assert restored.revision == handover.revision
    assert all(0 < budget < 2048 for budget in summary.budgets)


async def test_no_file_tools_means_no_checkpoint_or_restore_injection():
    model = ScriptedModel(["A", "B", "C"])
    agent = Agent(model=model, plugins=[TaskMemory(fallback_tokens=1)])
    async with agent.session() as session:
        for prompt in ("First", "Second", "Third"):
            result = await session.run(prompt)
    assert not any(isinstance(e, TaskMemoryEvent) for e in result.events)
    assert all(
        "Context compaction is approaching" not in r.messages[-1].text
        for r in model.requests
    )


async def test_separate_llm_and_async_prompt_preserve_native_retry_and_usage(tmp_path):
    seen = []
    fire = iter([False, False, True, *[False] * 10])

    async def prompt(context):
        seen.append(context)
        return "Preserve source URLs and unconfirmed actions."

    summary = ScriptedModel(
        [
            ModelResponse(
                AssistantMessage("Partial"), ModelUsage(100, 512), StopReason.MAX_TOKENS
            ),
            ModelResponse(AssistantMessage("Earlier findings."), ModelUsage(100, 20)),
        ]
    )
    model = ScriptedModel(
        [
            call("write_file", path="scratch.txt", content="old " * 2000),
            _save(),
            call("read_file", path=_PATH),
            "Finished",
        ]
    )
    memory = TaskMemory(
        trigger=lambda _state: next(fire),
        fallback_tokens=1,
        llm=summary,
        prompt=prompt,
        keep_last_steps=1,
        target_tokens=8000,
        max_summary_tokens=512,
    )
    async with Agent(
        model=model, plugins=_plugins(tmp_path, memory)
    ).session() as session:
        result = await session.run("Compare products", max_steps=8)
    assert result.text == "Finished"
    applied = [e for e in result.events if isinstance(e, CompactionAppliedEvent)]
    assert len(applied) == 1
    assert "Task memory handover:" in applied[0].summary
    assert "Partial" not in applied[0].summary
    assert len(summary.requests) == len(seen) == 2
    assert seen[0] is seen[1]
    assert seen[0].history_to_compact and seen[0].retained_context
    assert seen[0].instructions and seen[0].target_tokens == 8000
    assert (
        summary.requests[0].messages[0].text
        == "Preserve source URLs and unconfirmed actions."
    )
    assert (
        summary.requests[1].settings.max_tokens
        == 2 * summary.requests[0].settings.max_tokens
    )
    assert result.usage.input_tokens == 200
    assert result.usage.output_tokens == 532


async def test_checkpoint_is_not_requested_on_the_last_available_steps(tmp_path):
    model = ScriptedModel(["Unfinished"])
    async with Agent(
        model=model, plugins=_plugins(tmp_path, TaskMemory(fallback_tokens=1))
    ).session() as session:
        result = await session.run("Large task", max_steps=2)
    assert not any(isinstance(e, TaskMemoryEvent) for e in result.events)
    assert (
        "Context compaction is approaching" not in model.requests[0].messages[-1].text
    )


async def test_missing_checkpoint_is_visible_and_does_not_stop_compaction(tmp_path):
    model = ScriptedModel(
        [
            call("write_file", path="scratch.txt", content="old " * 2000),
            call("list_files"),
            "Unfinished",
        ],
        info=ModelInfo("test"),
    )
    memory = TaskMemory(
        trigger=lambda _state: True,
        fallback_tokens=1,
        summarizer=_Summary(),
        keep_last_steps=1,
        max_summary_tokens=2048,
    )
    async with Agent(
        model=model, plugins=_plugins(tmp_path, memory)
    ).session() as session:
        result = await session.run("Compare products", max_steps=8)
        state = session.scope[TaskMemory].current
    handover = next(
        e
        for e in result.events
        if isinstance(e, TaskMemoryEvent) and e.action is MemoryAction.COMPACTED
    )
    assert handover.revision is None and handover.checkpoint_saved is False
    assert state.restore_pending and not (tmp_path / _PATH).exists()


async def test_pending_read_survives_snapshot_and_store_reopen_without_copying_notes(
    tmp_path,
):
    workspace = tmp_path / "files"
    store = JsonSessionStore(root=tmp_path / "sessions")
    model = ScriptedModel(
        [
            call("write_file", path="scratch.txt", content="old " * 2000),
            _save(),
            "Paused",
        ],
        info=ModelInfo("test"),
    )
    memory = TaskMemory(
        trigger=lambda _state: True,
        fallback_tokens=1,
        summarizer=_Summary(),
        keep_last_steps=1,
        max_summary_tokens=2048,
    )
    async with Agent(
        model=model, plugins=_plugins(workspace, memory), store=store
    ).session(id="task") as session:
        await session.run("Compare products", max_steps=8)
        saved = session.snapshot().to_json()
        previous = session.scope[TaskMemory].current
    assert previous.restore_pending

    reader = ScriptedModel([call("read_file", path=_PATH), "Resumed"])
    agent = Agent(model=reader, plugins=_plugins(workspace, TaskMemory()), store=store)
    async with agent.session(id="task") as session:
        await session.run("Continue")
        state = session.scope[TaskMemory].current
    assert not state.restore_pending and state.revision == previous.revision
    assert "Read the saved working state" in reader.requests[0].messages[-1].text
    assert _NOTES not in reader.requests[0].messages[-1].text

    snapshot_reader = ScriptedModel([call("read_file", path=_PATH), "Restored"])
    agent = Agent(model=snapshot_reader, plugins=_plugins(workspace, TaskMemory()))
    async with agent.session(state=SessionState.from_json(saved)) as session:
        await session.run("Continue")
        assert not session.scope[TaskMemory].current.restore_pending
    async with agent.session() as session:
        assert session.scope[TaskMemory].current.revision is None


@pytest.mark.parametrize("read_args", [{"max_chars": 5}, {"offset": 5}])
async def test_partial_read_does_not_acknowledge_restoration(tmp_path, read_args):
    model = ScriptedModel(
        [
            call("write_file", path="scratch.txt", content="old " * 2000),
            _save(),
            call("read_file", path=_PATH, **read_args),
            "Paused",
        ],
        info=ModelInfo("test"),
    )
    memory = TaskMemory(
        trigger=lambda _state: True,
        fallback_tokens=1,
        summarizer=_Summary(),
        keep_last_steps=1,
        max_summary_tokens=2048,
    )
    async with Agent(
        model=model, plugins=_plugins(tmp_path, memory)
    ).session() as session:
        result = await session.run("Compare products", max_steps=8)
        assert session.scope[TaskMemory].current.restore_pending
    assert any(
        isinstance(e, TaskMemoryEvent) and e.action is MemoryAction.PARTIAL_READ
        for e in result.events
    )


async def test_normal_small_task_has_no_dynamic_memory_messages(tmp_path):
    model = ScriptedModel(["Finished"])
    async with Agent(
        model=model, plugins=_plugins(tmp_path, TaskMemory())
    ).session() as session:
        prompt = await session.prompt.render()
        result = await session.run("Simple task")
        assert await session.prompt.render() == prompt
    assert model.requests[0].messages[-1].text == "Simple task"
    assert not any(isinstance(e, TaskMemoryEvent) for e in result.events)
    assert not (tmp_path / _PATH).exists()


@pytest.mark.parametrize("content", ["", "large " * 3000])
async def test_empty_or_oversized_notes_do_not_count_as_a_checkpoint(tmp_path, content):
    model = ScriptedModel([_save(content), "Finished"])
    async with Agent(
        model=model, plugins=_plugins(tmp_path, TaskMemory())
    ).session() as session:
        result = await session.run("Save notes")
        assert session.scope[TaskMemory].current.revision is None
    receipts = [e for e in result.events if isinstance(e, TaskMemoryEvent)]
    assert len(receipts) == 1 and receipts[0].action is MemoryAction.UNAVAILABLE
    assert not receipts[0].checkpoint_saved


async def test_editing_notes_records_the_new_revision(tmp_path):
    model = ScriptedModel(
        [
            _save(),
            call(
                "edit_file",
                path=_PATH,
                old_text="Not purchased.",
                new_text="Purchased; confirmation checked.",
            ),
            "Finished",
        ]
    )
    async with Agent(
        model=model, plugins=_plugins(tmp_path, TaskMemory())
    ).session() as session:
        result = await session.run("Update notes")
        current = session.scope[TaskMemory].current
    saved = [
        e
        for e in result.events
        if isinstance(e, TaskMemoryEvent) and e.action is MemoryAction.SAVED
    ]
    assert len(saved) == 2 and saved[0].revision != saved[1].revision
    expected = _NOTES.replace("Not purchased.", "Purchased; confirmation checked.")
    assert (
        current.revision
        == saved[1].revision
        == hashlib.sha256(expected.encode()).hexdigest()
    )


async def test_known_window_uses_ratio_instead_of_unknown_window_fallback(tmp_path):
    model = ScriptedModel(
        ["Finished"], info=ModelInfo("test", context_window=1_000_000)
    )
    memory = TaskMemory(fallback_tokens=1)
    result = await Agent(model=model, plugins=_plugins(tmp_path, memory)).run(
        "Simple task"
    )
    assert not any(isinstance(e, TaskMemoryEvent) for e in result.events)


@pytest.mark.parametrize(
    "options",
    [
        {"path": "../outside.md"},
        {"path": "notes/file.txt"},
        {"path": 'notes/"a.md'},
        {"warn_at": 0},
        {"warn_at": 0.9},
        {"warn_at": True},
        {"fallback_tokens": 0},
        {"fallback_tokens": True},
    ],
)
def test_invalid_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        TaskMemory(**options)
