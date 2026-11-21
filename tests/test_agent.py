import pytest
from harnessed import Compaction, Context
from harnessed.context.budget import ContextBudget
from harnessed.context.compaction import CompactionPolicy
from harnessed.models import ModelInfo
from harnessed.testing import ScriptedModel

from browserrig import Agent, TaskMemory


def _without_browser():
    return tuple(
        type(plugin)
        for plugin in Agent(model=ScriptedModel([])).plugins
        if type(plugin).__module__.startswith("browserrig.")
        and not isinstance(plugin, TaskMemory)
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
    async with Agent(
        model=model,
        without=_without_browser(),
        context=Context(
            max_tokens=64_000,
            reserve_tokens=4096,
            compaction=Compaction(target_tokens=16_000, fallback_tokens=100_000),
        ),
    ).session() as session:
        assert session.scope[ContextBudget].window_limit(None) == 64_000
        assert session.scope[ContextBudget].reserve_tokens == 4096
        assert session.scope[CompactionPolicy].settings.target_tokens == 16_000
        assert session.scope[CompactionPolicy].settings.target_ratio is None
        assert (await session.run("Inspect")).text == "Done"


@pytest.mark.parametrize("instructions", ["Keep concise notes.", None])
async def test_default_plugin_can_override_or_omit_its_prompt(instructions):
    original = TaskMemory(path="notes/custom.md")
    configured = (
        original.without_instructions()
        if instructions is None
        else original.with_instructions(instructions)
    )
    async with Agent(
        model=ScriptedModel([]), without=_without_browser(), plugins=[configured]
    ).session() as session:
        prompt = await session.prompt.render()
        assert session.scope[TaskMemory].current.path == "notes/custom.md"
    async with Agent(
        model=ScriptedModel([]), without=_without_browser(), plugins=[original]
    ).session() as session:
        assert "Task working memory" in await session.prompt.render()

    assert "Task working memory" not in prompt
    assert ("Keep concise notes." in prompt) is (instructions is not None)
