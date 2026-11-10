import pytest
from harnessed.core.compaction import SummaryError
from harnessed.core.tokens import ApproximateTokenCounter
from harnessed.models import ModelUsage
from harnessed.plugins import ContextState
from harnessed.services import CompactionContext, CompactionRequest, Summary

from browserrig.memory.compaction import (
    CheckpointTrigger,
    MemoryRuntime,
    MemorySummarizer,
)


@pytest.mark.parametrize(
    "tokens, window, first",
    [
        (800, 1000, False),
        (900, 1000, True),
        (1100, 1000, True),
        (800, None, False),
    ],
)
def test_deferral_is_single_use_and_does_not_override_emergency_threshold(
    tokens, window, first
):
    calls = []

    def due(state):
        calls.append(state)
        return True

    trigger = CheckpointTrigger(due, MemoryRuntime(defer_once=True))
    state = ContextState(tokens, 0, window, 0)
    assert trigger(state) is first
    assert trigger(state) is True
    assert calls == [state, state]


async def test_summary_reserves_prefix_space_and_preserves_usage():
    usage = ModelUsage(input_tokens=100, output_tokens=20)
    summary = _Summary(Summary("Requirements and findings.", usage))
    runtime = MemoryRuntime(can_read=True)
    wrapped = MemorySummarizer(
        summary, ApproximateTokenCounter(), "notes/task_state.md", runtime
    )
    context = CompactionContext((), (), (), ContextState(1000, 100, 2000, 1), 800)
    request = CompactionRequest(context, 512)
    result = await wrapped.summarize(request)
    assert result.text.startswith("Task memory handover:")
    assert result.text.endswith("Requirements and findings.")
    assert result.usage is usage
    assert len(summary.budgets) == 1 and 0 < summary.budgets[0] < 512
    assert summary.requests[0].context is context
    assert request.max_summary_tokens == 512


async def test_tiny_summary_budget_is_preserved_for_summary_instead_of_only_a_hint():
    summary = _Summary(Summary("Important facts."))
    runtime = MemoryRuntime(can_read=True)
    wrapped = MemorySummarizer(
        summary, ApproximateTokenCounter(), "notes/task_state.md", runtime
    )
    result = await wrapped.summarize(_request(10))
    assert result.text == "Important facts."
    assert summary.budgets == [10]
    assert not runtime.inline_restore


async def test_handover_prefix_cannot_turn_an_empty_summary_into_a_valid_one():
    wrapped = MemorySummarizer(
        _Summary(Summary("")),
        ApproximateTokenCounter(),
        "notes/task_state.md",
        MemoryRuntime(can_read=True),
    )
    with pytest.raises(ValueError, match="empty summary"):
        await wrapped.summarize(_request(512))


async def test_invalid_summary_retains_incurred_usage_for_native_accounting():
    usage = ModelUsage(input_tokens=100, output_tokens=20)
    wrapped = MemorySummarizer(
        _Summary(Summary("", usage)),
        ApproximateTokenCounter(),
        "notes/task_state.md",
        MemoryRuntime(can_read=True),
    )
    with pytest.raises(SummaryError) as error:
        await wrapped.summarize(_request(512))
    assert error.value.usage is usage


class _Summary:
    def __init__(self, result):
        self.result = result
        self.budgets = []
        self.requests = []

    async def summarize(self, request):
        self.requests.append(request)
        self.budgets.append(request.max_summary_tokens)
        return self.result


def _request(budget):
    return CompactionRequest(
        CompactionContext((), (), (), ContextState(1000, 0, 2000, 1), None), budget
    )
