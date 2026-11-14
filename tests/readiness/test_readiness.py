# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import Agent, Plugin, hook
from harnessed.hooks import Next
from harnessed.kernel import PluginScope, needs
from harnessed.testing import ScriptedModel

from browserrig import (
    CheckReadiness,
    DomReady,
    DownloadReadiness,
    Readiness,
    ReadinessCheck,
    ReadinessOptions,
    SelectReadiness,
    wait_for_page,
)
from browserrig.core import ReadinessError, ReadinessPhase
from browserrig.events import ReadinessDegradedEvent, ReadinessStartedEvent, ReadyEvent
from browserrig.files import Download
from browserrig.observation import capture
from browserrig.readiness import probe_dom
from browserrig.readiness import wait as wait_module
from browserrig.scripts import STABILITY, DOMProbe
from tests.fakes import FakeBrowser, FakeChrome, FakeTab


class Access(Plugin, needs=(Readiness,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    _setup_readiness = needs(Readiness)

    async def setup(self, _ctx: PluginScope):
        readiness = self._setup_readiness
        self.holder["readiness"] = readiness


async def test_readiness_deduplicates_waiters_and_one_cancellation_does_not_cancel_other():
    holder = {}
    options = ReadinessOptions(quiet_ms=0, navigation_min_ms=40, poll_interval=0.005)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options), Access(holder)],
    )
    async with agent.session() as session:
        readiness, tab = holder["readiness"], holder["browser"].active_tab
        first = asyncio.create_task(readiness.wait(tab, phase="initial"))
        second = asyncio.create_task(readiness.wait(tab, phase="initial"))
        await asyncio.sleep(0.005)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 5)
        report = await asyncio.wait_for(second, 5)
        assert report.status == "ready"
        assert (
            len([e for e in session.events if isinstance(e, ReadinessStartedEvent)])
            == 1
        )


async def test_endless_dom_mutation_is_explicitly_degraded():
    holder = {}
    options = ReadinessOptions(timeout=0.03, poll_interval=0.005, navigation_min_ms=0)
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options), Access(holder)],
    )
    async with agent.session() as session:
        holder["browser"].active_tab.quiet_ms = 0
        report = await holder["readiness"].wait(holder["browser"].active_tab)
        assert report.status == "degraded"
        assert "changing" in report.reason
        assert any(isinstance(e, ReadinessDegradedEvent) for e in session.events)


async def test_plugin_state_is_per_session():
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[Access(holder), Readiness(), FakeChrome(holder)],
    )
    async with agent.session():
        first = holder["readiness"]
        first_events = first._events
        assert first_events is holder["browser"].events
        first._state.initialized.add(("sentinel", "doc"))
    async with agent.session():
        second = holder["readiness"]
        assert second is not first
        assert second._events is holder["browser"].events
        assert second._events is not first_events
        assert not second._state.initialized
    with pytest.raises(RuntimeError):
        _ = first._events


async def test_readiness_events_keep_start_document_when_navigation_finishes(
    monkeypatch,
):
    events = []
    browser = FakeBrowser(SimpleNamespace(emit=AsyncMock(side_effect=events.append)))
    tab = browser.active_tab

    async def check(_strategy):
        checked.append(tab.document_id)
        tab.document_id = "new-document"
        return True

    checked = []
    monkeypatch.setattr(wait_module, "_check", check)
    report = await wait_for_page(tab, events=browser.events)
    start = next(event for event in events if isinstance(event, ReadinessStartedEvent))
    end = next(event for event in events if isinstance(event, ReadyEvent))
    assert start.readiness_id == end.readiness_id
    assert start.document_id == end.document_id == "doc-1"
    assert report.document_id == "new-document"
    assert checked == ["doc-1", "new-document"]


@pytest.mark.parametrize("blocked", ["sync", "selection", "middleware", "dispatch"])
async def test_deadline_includes_document_sync_and_native_extension_work(blocked):
    tab = FakeTab()

    async def pending(*_args):
        await asyncio.Event().wait()

    kwargs = {}
    if blocked == "sync":
        tab.sync_document = pending
    elif blocked == "selection":
        kwargs["select"] = pending
    elif blocked == "dispatch":
        kwargs["dispatch"] = pending
    else:
        kwargs["check"] = pending
    async with asyncio.timeout(0.5):
        report = await wait_for_page(tab, options=_fast_options(), **kwargs)
    assert report.status == "degraded" and report.timed_out
    assert "budget exhausted" in report.reason


async def test_redirect_chain_restarts_probes_without_extending_the_deadline(
    monkeypatch,
):
    tab = FakeTab()
    checked, selected = [], []

    async def redirect(strategy):
        checked.append(strategy)
        if len(checked) == 3:
            # Yield only after two redirects; timer granularity must not decide
            # how many documents this test exercises.
            await asyncio.Event().wait()
        tab.document_id += "x"
        return True

    async def select(context):
        selected.append((context.tab.document_id, context.deadline))
        return DomReady()

    monkeypatch.setattr(wait_module, "_check", redirect)
    async with asyncio.timeout(5):
        report = await wait_for_page(tab, options=_fast_options(), select=select)
    assert report.timed_out and report.status == "degraded"
    assert [document for document, _ in selected] == ["doc-1", "doc-1x", "doc-1xx"]
    assert len({id(strategy) for strategy in checked}) == 3
    assert len({deadline for _, deadline in selected}) == 1


async def test_after_action_requires_fresh_observation_time_even_when_dom_was_quiet():
    options = _fast_options(timeout=0.2, quiet_ms=5, action_min_ms=30)
    task = asyncio.create_task(
        wait_for_page(FakeTab(), options=options, phase=ReadinessPhase.AFTER_ACTION)
    )
    await asyncio.sleep(0.01)
    assert not task.done()
    assert (await asyncio.wait_for(task, 5)).status == "ready"


async def test_pending_navigation_is_not_ready_using_the_old_document():
    tab = FakeTab()
    tab.navigation_pending = True
    report = await wait_for_page(tab, options=_fast_options())
    assert report.timed_out and "navigation" in report.reason


@pytest.mark.parametrize("changed_during", ["sync", "dispatch"])
async def test_document_discovered_during_sync_or_dispatch_uses_initial_policy_again(
    changed_during,
):
    selected = []

    class Selection(Plugin):
        @hook(SelectReadiness)
        def select(self, event: SelectReadiness):
            selected.append((event.context.tab.document_id, event.context.stage))

    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=_fast_options()), Selection()],
    )
    async with agent.session() as session:
        readiness, tab = session.scope[Readiness], holder["browser"].active_tab
        await readiness.wait(tab)

        async def sync():
            tab.document_id = "new-document"

        if changed_during == "sync":
            tab.sync_document = sync
            report = await readiness.wait(tab)
        else:
            report = await readiness.wait(tab, dispatch=sync)
        assert report.stage == "initial"
        assert selected == [("doc-1", "initial"), ("new-document", "initial")]


async def test_navigation_dispatches_execute_once_each_and_do_not_share_a_readonly_wait():
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=_fast_options(timeout=0.2))],
    )
    async with agent.session() as session:
        readiness, tab = session.scope[Readiness], holder["browser"].active_tab
        commands = [AsyncMock(), AsyncMock()]
        reports = await asyncio.gather(
            *(
                readiness.wait(tab, phase=ReadinessPhase.NAVIGATION, dispatch=command)
                for command in commands
            )
        )
        assert all(command.await_count == 1 for command in commands)
        assert reports[0].id != reports[1].id


async def test_cancelling_a_dispatch_cancels_its_owned_work():
    holder = {}
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def dispatch():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=_fast_options(timeout=1))],
    )
    async with agent.session() as session:
        task = asyncio.create_task(
            session.scope[Readiness].wait(
                holder["browser"].active_tab, dispatch=dispatch
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert cancelled.is_set()


async def test_strict_readiness_remains_available():
    tab = FakeTab()
    tab.navigation_pending = True
    with pytest.raises(ReadinessError, match="timed out"):
        await wait_for_page(tab, options=_fast_options(allow_degraded_dom=False))


async def test_native_policy_selection_and_waterfall_are_removed_with_the_plugin():
    chosen = []
    checked = []
    options = _fast_options()
    policy = DomReady(options)

    class ApplicationReadiness(Plugin):
        @hook(SelectReadiness)
        def select(self, event: SelectReadiness):
            chosen.append(event.context.stage)
            return policy

        @hook(CheckReadiness)
        async def check(self, event: CheckReadiness, next_: Next[ReadinessCheck]):
            result = await next_()
            checked.append((result.ready, event.context.remaining))
            return ReadinessCheck(False, "Application data is still loading")

    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[FakeChrome(holder), Readiness(options=options)],
    )
    async with agent.session() as session:
        extension = await session.mount(ApplicationReadiness())
        readiness, tab = session.scope[Readiness], holder["browser"].active_tab
        report = await readiness.wait(tab)
        assert report.timed_out and "Application data" in report.reason
        assert chosen == ["initial"]
        # The hook can finish exactly as the budget expires on coarse clocks.
        assert checked and all(ready and remaining >= 0 for ready, remaining in checked)
        await extension.aclose()
        assert (await readiness.wait(tab)).status == "ready"


async def test_download_timeout_is_delivered_to_observation_without_another_wait():
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Readiness(options=_fast_options()),
            DownloadReadiness(),
        ],
    )
    async with agent.session() as session:
        browser = holder["browser"]
        browser.downloads = AsyncMock(
            return_value=(
                Download(id="download", filename="test.pdf", url="https://example.org"),
            )
        )
        readiness, tab = session.scope[Readiness], browser.active_tab
        report = await readiness.wait(tab, phase=ReadinessPhase.AFTER_ACTION)
        assert report.timed_out and "download" in report.reason
        command = AsyncMock()
        with pytest.raises(ReadinessError, match="inspect the next observation"):
            await readiness.wait(tab, dispatch=command)
        command.assert_not_awaited()
        probes = tab.probes
        repeated = await readiness.wait(tab, phase=ReadinessPhase.ACTION)
        observed = await readiness.wait(tab)
        assert repeated.id == observed.id == report.id
        assert tab.probes == probes
        browser.downloads.return_value = ()
        retried = await readiness.wait(tab)
        assert retried.status == "ready" and not retried.timed_out


async def test_active_downloads_can_finish_during_the_shared_wait():
    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Readiness(options=_fast_options(timeout=0.2)),
            DownloadReadiness(),
        ],
    )
    async with agent.session() as session:
        browser = holder["browser"]
        browser.downloads = AsyncMock(
            side_effect=[
                (Download(id="d", filename="x", url="https://example.org"),),
                (),
            ]
        )
        report = await session.scope[Readiness].wait(browser.active_tab)
        assert report.status == "ready" and browser.downloads.await_count == 2


async def test_successive_checks_share_the_remaining_budget_until_observation(
    monkeypatch,
):
    budgets = []
    elapsed = 0.0
    loop = asyncio.get_running_loop()

    def monotonic():
        return loop.time() + elapsed

    # Python 3.12 on Windows can report zero duration for an immediate probe.
    # Account for controlled probe time without depending on clock resolution.
    monkeypatch.setattr(wait_module, "monotonic", monotonic)

    class RecordBudget(Plugin):
        @hook(CheckReadiness)
        async def check(self, event: CheckReadiness, next_: Next[ReadinessCheck]):
            nonlocal elapsed
            budgets.append(event.context.remaining)
            elapsed += 0.25
            return await next_()

    holder = {}
    agent = Agent(
        model=ScriptedModel(["ok"]),
        plugins=[
            FakeChrome(holder),
            Readiness(options=_fast_options(timeout=2)),
            RecordBudget(),
        ],
    )
    async with agent.session() as session:
        readiness, tab = session.scope[Readiness], holder["browser"].active_tab
        first = await readiness.wait(tab, phase=ReadinessPhase.ACTION)
        second = await readiness.wait(tab, phase=ReadinessPhase.AFTER_ACTION)
        assert first.status == second.status == "ready"
        assert 0 < budgets[1] < budgets[0] <= 2
        assert budgets[1] <= 2 - first.duration
        await readiness.wait(tab)
        assert tab.id not in readiness._state.spent


async def test_timed_out_capture_has_a_bounded_fallback_without_stale_controls():
    tab = FakeTab()
    tab.navigation_pending = True
    report = await wait_for_page(tab, options=_fast_options())
    tab.sync_document = AsyncMock(side_effect=ReadinessError("renderer unavailable"))
    snapshot = await capture(tab, SimpleNamespace(), report, screenshots=True)
    assert (
        snapshot.readiness == "degraded" and snapshot.readiness_reason == report.reason
    )
    assert not snapshot.elements and snapshot.image is None
    assert "still loading" in snapshot.text


async def test_dom_probe_combines_child_activity_and_preserves_main_geometry():
    main_state = DOMProbe(
        loaded=True,
        body=True,
        quiet_ms=100,
        width=1280,
        height=800,
        unobserved_frames=2,
        animations=1,
    )
    child_state = DOMProbe(
        loaded=False,
        body=True,
        quiet_ms=20,
        width=300,
        height=200,
        animations=2,
        busy=True,
    )
    main = SimpleNamespace(id="main", run=AsyncMock(return_value=main_state))
    child = SimpleNamespace(id="child", run=AsyncMock(return_value=child_state))
    tab = SimpleNamespace(
        main_frame=AsyncMock(return_value=main),
        frames=AsyncMock(return_value=(main, child)),
        frame_limitations=("A frame was detached",),
    )
    state = await probe_dom(tab)
    assert state == DOMProbe(
        loaded=False,
        body=True,
        quiet_ms=20,
        width=1280,
        height=800,
        unobserved_frames=2,
        animations=3,
        busy=True,
        limited=True,
    )
    main.run.assert_awaited_once_with(STABILITY)
    child.run.assert_awaited_once_with(STABILITY)
    tab.frames.assert_awaited_once_with()


async def test_dom_probe_keeps_the_main_state_when_no_child_can_be_discovered():
    state = DOMProbe(
        loaded=True, body=True, quiet_ms=40, width=800, height=600, unobserved_frames=1
    )
    main = SimpleNamespace(id="main", run=AsyncMock(return_value=state))
    tab = SimpleNamespace(
        main_frame=AsyncMock(return_value=main),
        frames=AsyncMock(return_value=(main,)),
        frame_limitations=(),
    )
    assert await probe_dom(tab) == state
    main.run.assert_awaited_once_with(STABILITY)


def _fast_options(**kwargs):
    return ReadinessOptions(
        **{
            "timeout": 0.05,
            "navigation_min_ms": 0,
            "action_min_ms": 0,
            "quiet_ms": 0,
            "poll_interval": 0.002,
            **kwargs,
        }
    )
