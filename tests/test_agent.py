import pytest
from harnessed.core.budget import ContextBudget
from harnessed.core.compaction import CompactionPolicy
from harnessed.models import ModelInfo
from harnessed.plugins import Service
from harnessed.testing import ScriptedModel

from browserrig import Agent, ContextCompaction, TaskMemory, browser_plugins


def _without_browser():
    return tuple(
        type(plugin)
        for plugin in browser_plugins()
        if not isinstance(plugin, TaskMemory)
    )


@pytest.mark.parametrize("provider", ["openai", "openai-codex"])
async def test_terra_uses_shared_context_budget_and_compaction_profile(provider):
    model = ScriptedModel(["Done"], info=ModelInfo("gpt-6.1-terra", provider=provider))
    agent = Agent(model=model, without=_without_browser())
    async with agent.session() as session:
        budget = session.scope[ContextBudget]
        assert budget.window_limit(model.info.context_window) == 256_000
        assert budget.reserve_tokens == 8192
        policy = session.scope[CompactionPolicy]
        assert policy.settings.keep_last_steps == 2
        assert policy.settings.target_ratio == 0.4
        assert policy.settings.max_summary_tokens == 8192
        result = await session.run("Inspect")
    assert result.text == "Done"


async def test_other_models_keep_their_existing_context_and_compaction_defaults():
    model = ScriptedModel(
        ["Done"], info=ModelInfo("another-model", context_window=32_000)
    )
    async with Agent(model=model, without=_without_browser()).session() as session:
        budget = session.scope[ContextBudget]
        assert budget.window_limit(model.info.context_window) == 32_000
        assert budget.reserve_tokens == 0
        assert session.scope[CompactionPolicy].settings.target_ratio is None
        assert session.scope[CompactionPolicy].settings.max_summary_tokens is None
        assert (await session.run("Inspect")).text == "Done"


async def test_explicit_budget_and_compaction_override_terra_defaults():
    model = ScriptedModel(["Done"], info=ModelInfo("gpt-6.1-terra"))
    budget = ContextBudget(limit=64_000, reserve_tokens=4096)
    async with Agent(
        model=model,
        without=_without_browser(),
        plugins=[
            Service(ContextBudget, budget),
            ContextCompaction(target_tokens=16_000),
        ],
    ).session() as session:
        assert session.scope[ContextBudget] is budget
        assert session.scope[CompactionPolicy].settings.target_tokens == 16_000
        assert session.scope[CompactionPolicy].settings.target_ratio is None
        assert (await session.run("Inspect")).text == "Done"
