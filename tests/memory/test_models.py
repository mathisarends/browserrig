from harnessed.events import EventRegistry
from pydantic import TypeAdapter

from browserrig import MemoryAction, TaskMemoryEvent
from browserrig.events import EventKind


def test_memory_event_preserves_its_wire_tag_and_restores_the_enum():
    event = TaskMemoryEvent(
        action=MemoryAction.SAVED,
        path="notes/task_state.md",
        revision="revision",
        compaction_id=None,
        checkpoint_saved=True,
        restore_pending=False,
    )
    adapter = TypeAdapter(TaskMemoryEvent)
    payload = adapter.dump_python(event, mode="json")
    assert payload["type"] == "browserrig.memory"
    assert payload["action"] == "saved"
    restored = adapter.validate_python(payload)
    registry = EventRegistry((TaskMemoryEvent,))
    assert registry.decode(registry.encode(restored)) == event
    assert restored.type is EventKind.TASK_MEMORY
