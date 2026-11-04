import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from harnessed import (
    Agent,
    Plugin,
    PluginOrder,
    PolicyDecision,
    SessionState,
    SystemPrompt,
    ToolStatus,
    tool,
)
from harnessed.core.prompt.context import DynamicContext
from harnessed.events import (
    CompactionAppliedEvent,
    EventRegistry,
    ToolCallFinishedEvent,
)
from harnessed.models import ModelChunk, ToolMessage
from harnessed.plugins import AgentLoop, Approvals, Compaction
from harnessed.testing import ScriptedModel, call

import browserrig
from browserrig import (
    Activity,
    BrowserPerception,
    HandoffReceipt,
    HumanHandoff,
    HumanResponse,
    Nudges,
    Readiness,
    ReadinessOptions,
    Secret,
    Secrets,
    browser_plugins,
)
from browserrig.browser import TabInfo
from browserrig.core import ActivityKind, ActivityOutcome
from browserrig.events import (
    BROWSER_EVENTS,
    HANDOFF_EVENTS,
    HandoffFinishedEvent,
    HandoffRequestedEvent,
    NudgeQueuedEvent,
    TabClosedEvent,
    TabOpenedEvent,
)
from browserrig.observation import CaptureContent, Element
from browserrig.observation.extraction import Extraction
from tests.fakes import FakeChrome
from tests.observations import latest


class _Capture:
    async def collect(self, tab, _report, **_options):
        return CaptureContent(
            page=Extraction(
                url=tab.url,
                title=tab.title,
                text="Dashboard" if tab.logged_in else "Please log in",
                width=800,
                height=600,
                scroll_y=0,
                page_height=600,
                elements=()
                if tab.logged_in
                else (
                    Element(
                        ref="1",
                        frame_id="frame",
                        backend_id=1,
                        role="textbox",
                        name="Password",
                        tag="input",
                        input_type="password",
                    ),
                ),
            ),
        )


class _Step(Plugin):
    events = BROWSER_EVENTS

    @tool(readonly=True)
    async def step(self) -> str:
        return "Advanced"


def _agent(responses, ask, *, extra=(), **options):
    holder = {}
    model = ScriptedModel(responses)
    agent = Agent(
        prompt=SystemPrompt.from_plugins(order=PluginOrder.AS_LISTED),
        model=model,
        plugins=[
            Activity(),
            FakeChrome(holder),
            Readiness(options=ReadinessOptions(navigation_min_ms=0)),
            *extra,
            BrowserPerception(capture=_Capture()),
            Nudges(),
            HumanHandoff(ask=ask, **options),
            _Step(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    return agent, model, holder


def _prepare(holder):
    browser = holder["browser"]
    browser.active_tab.title = "Login"
    browser.active_tab.logged_in = False
    browser.tabs.list = AsyncMock(
        side_effect=lambda: (
            TabInfo(
                id=browser.active_tab.id,
                url=browser.active_tab.url,
                title=browser.active_tab.title,
                active=True,
            ),
        )
    )
    return browser


def _request():
    return call(
        "request_human", reason="Please log in", expected_state="Dashboard visible"
    )


def _receipt(request):
    return next(
        json.loads(message.text)
        for message in request.messages
        if isinstance(message, ToolMessage) and '"handoff_id"' in message.text
    )


async def test_handoff_reports_navigation_transient_popup_and_human_note():
    async def ask(request):
        assert request.reason == "Please log in"
        browser = holder["browser"]
        await browser.events.emit(
            TabOpenedEvent(target_id="oauth", url="https://id.example/")
        )
        await browser.events.emit(TabClosedEvent(target_id="oauth"))
        await session.ctx[Nudges].queue(
            "stale no progress", key="no_progress", cause_id="old"
        )
        browser.active_tab.url = "https://example.org/dashboard?token=sensitive#secret"
        browser.active_tab.document_id = "doc-2"
        browser.active_tab.title = "Dashboard"
        browser.active_tab.logged_in = True
        return HumanResponse(note="Logged in and confirmed 2FA")

    agent, model, holder = _agent([_request(), "Done"], ask)
    async with agent.session() as session:
        _prepare(holder)
        result = await session.run("Open my dashboard")
        history = json.loads(session.ctx[DynamicContext].values["browser.handoffs"])
        intervals = session.ctx[Activity].intervals()
    receipt = _receipt(model.requests[-1])
    assert receipt == history[-1]
    assert receipt["status"] == "done"
    assert receipt["human_note"] == "Logged in and confirmed 2FA"
    assert receipt["current_url"] == "https://example.org/dashboard"
    assert any("tab.opened" in change for change in receipt["changes"])
    assert any("tab.closed" in change for change in receipt["changes"])
    assert "sensitive" not in json.dumps(receipt)
    assert latest(model.requests[-1].messages)["page"]["title"] == "Dashboard"
    assert not any(isinstance(event, NudgeQueuedEvent) for event in result.events)
    handoff = next(item for item in intervals if item.kind is ActivityKind.HANDOFF)
    assert handoff.outcome is ActivityOutcome.COMPLETED
    assert all(
        item.at <= handoff.started_at or item.started_at >= handoff.at
        for item in intervals
        if item.kind is ActivityKind.TOOL
    )


async def test_done_without_a_note_or_page_change_does_not_claim_login_success():
    agent, model, holder = _agent(
        [_request(), "Done"], AsyncMock(return_value=HumanResponse())
    )
    async with agent.session() as session:
        _prepare(holder)
        await session.run("Log in")
    receipt = _receipt(model.requests[-1])
    assert receipt["status"] == "done" and receipt["human_note"] == ""
    assert any(
        "password field is still visible" in change for change in receipt["changes"]
    )
    assert "not verified" in receipt["next"]
    # Even an unchanged page is delivered in full after control returns.
    assert (
        sum(
            message.text.startswith("# Login")
            for message in model.requests[-1].messages
        )
        == 2
    )


async def test_failed_comparison_still_returns_a_typed_receipt_and_refreshes_the_page():
    async def ask(_request):
        session.ctx[BrowserPerception].probe = AsyncMock(
            side_effect=RuntimeError("Capture unavailable")
        )
        holder["browser"].active_tab.title = "Changed by human"
        return HumanResponse()

    agent, model, holder = _agent([_request(), "Done"], ask)
    async with agent.session() as session:
        _prepare(holder)
        await session.ctx[DynamicContext].set(
            "browser.handoffs", '[{"status":"invalid"}]'
        )
        await session.run("Log in")
        history = json.loads(session.ctx[DynamicContext].values["browser.handoffs"])
    receipt = HandoffReceipt.model_validate(_receipt(model.requests[-1]))
    assert receipt.status == "done" and receipt.current_url is None
    assert "could not be captured" in receipt.changes[0]
    assert len(history) == 1
    assert latest(model.requests[-1].messages)["page"]["title"] == "Changed by human"


@pytest.mark.parametrize(
    "outcome", ["declined", "timeout", "failed", "invalid_response"]
)
async def test_unsuccessful_handoffs_release_browser_and_hint_state(outcome):
    async def ask(_request):
        if outcome == "timeout":
            await asyncio.Event().wait()
        if outcome == "failed":
            raise RuntimeError("private host error")
        if outcome == "invalid_response":
            return None
        return HumanResponse(status="declined")

    agent, model, holder = _agent([_request(), "Done"], ask, timeout=0.02)
    async with agent.session() as session:
        browser = _prepare(holder)
        result = await session.run("Log in")
        assert not browser.action_lock.locked()
        await session.ctx[Nudges].queue("After handoff", key="after", cause_id="after")
        assert session.log.last(NudgeQueuedEvent).text == "After handoff"
    expected = "failed" if outcome == "invalid_response" else outcome
    assert _receipt(model.requests[-1])["status"] == expected
    assert any(
        isinstance(event, HandoffFinishedEvent) and event.status == expected
        for event in result.events
    )
    assert "private host error" not in str(model.requests)


async def test_handoff_has_its_own_timeout_and_stops_trailing_tool_calls():
    async def ask(_request):
        await asyncio.sleep(0.04)
        return HumanResponse()

    first, trailing = _request(), call("step")
    batch = [
        ModelChunk(tool_call=tool_call)
        for response in (first, trailing)
        for tool_call in response.message.tool_calls
    ]
    agent, model, holder = _agent(
        [batch, "Done"],
        ask,
        timeout=1,
        extra=(AgentLoop(tool_timeout=0.01),),
    )
    async with agent.session() as session:
        _prepare(holder)
        result = await session.run("Log in")
    assert _receipt(model.requests[-1])["status"] == "done"
    replies = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert replies[0].break_chain and replies[1].status is ToolStatus.SKIPPED


@pytest.mark.parametrize("track_pauses", [True, False])
async def test_pause_resume_explains_external_changes_without_steering(track_pauses):
    callback = AsyncMock(return_value=HumanResponse())
    agent, model, holder = _agent(["Done"], callback, track_pauses=track_pauses)
    async with agent.session() as session:
        browser = _prepare(holder)
        await session.pause()
        browser.active_tab.title = "Changed by human"
        await session.resume()
        result = await session.run("Continue")
        history = json.loads(
            session.ctx[DynamicContext].values.get("browser.handoffs", "[]")
        )
    callback.assert_not_called()
    assert latest(model.requests[-1].messages)["page"]["title"] == "Changed by human"
    if track_pauses:
        assert history[-1]["status"] == "resumed" and history[-1]["source"] == "pause"
        assert any("Changed by human" in change for change in history[-1]["changes"])
        assert any(isinstance(event, HandoffFinishedEvent) for event in result.events)
    else:
        assert not history
        assert not any(
            isinstance(event, HandoffFinishedEvent) for event in result.events
        )


async def test_running_pause_cannot_lose_a_resume_while_a_probe_is_slow(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    class Gate(Plugin):
        @tool(readonly=True)
        async def hold(self) -> str:
            started.set()
            await release.wait()
            return "Step finished"

    agent, _model, holder = _agent(
        [call("hold"), "Done"], AsyncMock(return_value=HumanResponse()), extra=(Gate(),)
    )
    async with agent.session() as session:
        browser = _prepare(holder)
        observe = session.ctx[BrowserPerception]
        probe = observe.probe

        async def slow_probe(tab):
            await asyncio.sleep(0.05)
            return await probe(tab)

        monkeypatch.setattr(observe, "probe", slow_probe)
        handle = await session.submit("Inspect")
        async with asyncio.timeout(5):
            await started.wait()
            pause = asyncio.create_task(session.pause())
            await asyncio.sleep(0)
            release.set()
            await pause
            browser.active_tab.title = "Changed after pause"
            await session.resume()
            await handle.result()
        history = json.loads(session.ctx[DynamicContext].values["browser.handoffs"])
        assert history[-1]["status"] == "resumed"
        assert any("Changed after pause" in change for change in history[-1]["changes"])


class _Summary:
    async def summarize(self, _messages, *, max_tokens):  # pylint: disable=unused-argument
        return "Earlier work summarized, without login details."


async def test_handoff_context_survives_compaction_and_session_restore():
    callback = AsyncMock(return_value=HumanResponse(note="2FA completed"))
    fire = iter([False, False, False, True, *[False] * 10])
    compaction = Compaction(
        trigger=lambda _state: next(fire),
        summarizer=_Summary(),
        keep_turns=0,
        keep_steps=1,
    )
    agent, model, holder = _agent(
        [_request(), call("step"), call("step"), call("step"), "Done", "Restored"],
        callback,
        extra=(compaction,),
    )
    async with agent.session() as session:
        _prepare(holder)
        result = await session.run("Log in")
        saved = session.snapshot().to_json()
        history = session.ctx[DynamicContext].values["browser.handoffs"]
    assert any(isinstance(event, CompactionAppliedEvent) for event in result.events)
    assert "2FA completed" in "\n".join(
        message.text for message in model.requests[-1].messages
    )
    assert not any(
        isinstance(message, ToolMessage) and '"handoff_id"' in message.text
        for message in model.requests[-1].messages
    )
    async with agent.session(state=SessionState.from_json(saved)) as restored:
        _prepare(holder)
        await restored.run("Continue")
        assert restored.ctx[DynamicContext].values["browser.handoffs"] == history
    assert callback.await_count == 1


async def test_handoff_history_is_bounded_and_known_secrets_are_redacted():
    password = "secret-not-for-context"
    callback = AsyncMock(return_value=HumanResponse(note=f"Done {password}"))
    secrets = Secrets({"pw": Secret(password, domains="example.org")})
    agent, _model, holder = _agent(
        [_request(), _request(), _request(), "Done"],
        callback,
        extra=(secrets,),
        history_limit=2,
    )
    async with agent.session() as session:
        _prepare(holder)
        result = await session.run("Log in")
        history = session.ctx[DynamicContext].values["browser.handoffs"]
    assert len(json.loads(history)) == 2
    assert password not in history and "{{secret:pw}}" in history
    assert all(
        password not in event.note
        for event in result.events
        if isinstance(event, HandoffFinishedEvent)
    )


async def test_abort_cancels_the_callback_and_releases_the_handoff():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def ask(_request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    agent, _model, holder = _agent([_request(), "Continued"], ask)
    async with agent.session() as session:
        browser = _prepare(holder)
        handle = await session.submit("Log in")
        async with asyncio.timeout(5):
            await started.wait()
            await session.abort()
            await handle.result()
        assert cancelled.is_set() and not browser.action_lock.locked()
        finished = session.log.last(HandoffFinishedEvent)
        assert finished.status == "cancelled"
        assert (
            json.loads(session.ctx[DynamicContext].values["browser.handoffs"])[-1][
                "status"
            ]
            == "cancelled"
        )
        await session.ctx[Nudges].queue("After abort", key="after", cause_id="after")
        assert session.log.last(NudgeQueuedEvent).text == "After abort"


async def test_handoff_is_opt_in_for_the_facade_and_explicit_composition():
    callback = AsyncMock(return_value=HumanResponse())
    handoff = HumanHandoff(ask=callback)
    default = browserrig.Agent(model=ScriptedModel(["Done"]))
    assert not any(isinstance(plugin, HumanHandoff) for plugin in default.plugins)
    assert "Use request_human" not in await default.prompt.render()
    assert not any(isinstance(plugin, HumanHandoff) for plugin in browser_plugins())
    configured = browserrig.Agent(model=ScriptedModel(["Done"]), plugins=[handoff])
    assert (
        handoff in configured.plugins
        and "Use request_human" in await configured.prompt.render()
    )
    assert handoff in browser_plugins(handoff)
    composed = browserrig.Agent(model=ScriptedModel(["Done"]), plugins=[handoff])
    assert handoff in composed.plugins


def test_handoff_events_roundtrip_with_typed_receipts():
    registry = EventRegistry(HANDOFF_EVENTS)
    for event in (
        HandoffRequestedEvent(handoff_id="id", reason="Log in"),
        HandoffFinishedEvent(
            handoff_id="id", status="done", changes=("Document changed",)
        ),
    ):
        assert registry.decode(registry.encode(event)) == event
