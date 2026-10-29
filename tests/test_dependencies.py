from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from harnessed import Agent, Context, Plugin, PluginValidation
from harnessed.core.tools.registry import ToolRegistry
from harnessed.errors import PluginDependencyError, PluginDependencyWarning
from harnessed.plugins import Service
from harnessed.testing import ScriptedModel

from browserrig import Actions, Browser, BrowserAgent, Observe, Readiness
from browserrig.tools import DialogTools, KeyboardTools
from tests.fakes import FakeBrowser


async def test_incomplete_browser_composition_reports_transitive_dependencies_before_model_use():
    model = ScriptedModel(["unused"])
    agent = Agent(
        model=model,
        plugins=[KeyboardTools(), Actions(), Observe(), Readiness(), DialogTools()],
    )
    with pytest.raises(PluginDependencyError) as caught:
        await agent.run("Inspect the page")
    missing = {issue.plugin.name: issue.missing for issue in caught.value.issues}
    assert missing == {
        "KeyboardTools": (Actions,),
        "Actions": (Browser, Readiness, Observe),
        "Observe": (Browser, Readiness),
        "Readiness": (Browser,),
        "DialogTools": (Browser,),
    }
    assert not model.requests


async def test_browser_dependency_loss_and_replacement_restart_observation_state():
    async with Context() as ctx:
        ctx.provide(ToolRegistry, ToolRegistry(ctx))
        await ctx.install([Observe(), Readiness()], settle=True)
        assert {issue.plugin.name for issue in ctx.plugin_diagnostics()} == {"Observe", "Readiness"}

        first_browser = FakeBrowser(None)
        remove_first = ctx.provide(Browser, first_browser)
        await ctx.settle()
        assert not ctx.plugin_diagnostics()
        first_readiness, first_observe = ctx[Readiness], ctx[Observe]
        assert first_readiness.browser is first_browser
        first_readiness.state.geometry[("sentinel", "doc")] = object()
        first_observe.state.snapshot = object()

        second_browser = FakeBrowser(None)
        remove_second = ctx.provide(Browser, second_browser)
        await ctx.settle()
        assert ctx[Readiness] is not first_readiness
        assert ctx[Observe] is not first_observe
        assert ctx[Observe].browser is ctx[Readiness].browser is second_browser
        assert ctx[Observe].readiness is ctx[Readiness]
        assert not ctx[Readiness].state.geometry
        assert ctx[Observe].snapshot is None
        with pytest.raises(RuntimeError):
            _ = first_observe.browser

        await remove_second()
        await ctx.settle()
        assert ctx[Readiness].browser is first_browser
        await remove_first()
        await ctx.settle()
        assert Readiness not in ctx and Observe not in ctx
        missing = {issue.plugin.name: issue.missing for issue in ctx.plugin_diagnostics()}
        assert missing == {"Readiness": (Browser,), "Observe": (Browser, Readiness)}


class _DeferredService:
    pass


@pytest.fixture(name="fake_chrome")
def _fake_chrome(monkeypatch):
    resources = []

    @asynccontextmanager
    async def open_browser(_options, *, emit):
        resource = SimpleNamespace(browser=FakeBrowser(SimpleNamespace(emit=emit)), closed=False)
        resources.append(resource)
        try:
            yield resource.browser
        finally:
            resource.closed = True

    monkeypatch.setattr("browserrig.browser.plugin.ChromeBrowser", open_browser)
    return resources


@pytest.mark.parametrize("use_run", [False, True])
async def test_facade_rejects_missing_services_and_closes_acquired_browser(fake_chrome, use_run):
    model = ScriptedModel(["unused"])
    agent = BrowserAgent(model=model, plugins=[Plugin(needs=(_DeferredService,))])
    with pytest.raises(PluginDependencyError) as caught:
        if use_run:
            await agent.run("Inspect the page")
        else:
            async with agent.session():
                pytest.fail("An incomplete composition must fail before opening")
    assert len(caught.value.issues) == 1
    assert caught.value.issues[0].missing == (_DeferredService,)
    assert not model.requests
    assert len(fake_chrome) == 1 and fake_chrome[0].closed


async def test_facade_warning_policy_keeps_deferred_plugin_until_service_is_added(fake_chrome):
    mounted = []

    class Deferred(Plugin, needs=(_DeferredService,)):
        async def setup(self):
            mounted.append(self)

    agent = BrowserAgent(
        model=ScriptedModel(["unused"]),
        plugins=[Deferred()],
        plugin_validation=PluginValidation.WARN,
    )
    with pytest.warns(PluginDependencyWarning) as warnings:
        async with agent.session() as session:
            assert not mounted
            handle = await session.use(Service(_DeferredService, _DeferredService()))
            assert len(mounted) == 1
            await handle.aclose()
    assert len(warnings) == 1
    assert warnings[0].message.issues[0].missing == (_DeferredService,)
    assert len(fake_chrome) == 1 and fake_chrome[0].closed
