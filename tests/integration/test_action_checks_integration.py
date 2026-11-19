import pytest
from harnessed import Plugin, PolicyDecision, ToolCall, hook
from harnessed.events import ToolCallFinishedEvent
from harnessed.kernel import PluginScope
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    ActionKind,
    Agent,
    AppState,
    Browser,
    BrowserPerception,
    Choreography,
    ChoreographyOverlay,
    Chrome,
    Generation,
    InputPacing,
    PageReadiness,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTrigger,
    wait_for_page,
)
from browserrig.core import ReadinessStatus, StaleElement
from browserrig.events import (
    ACTION_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
)
from browserrig.observation import CapturedImage, Snapshot
from browserrig.tools import CheckAction
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_board_revision_check_rejects_stale_screenshot_then_allows_click(site):
    steps = 0

    async def respond(_request):
        nonlocal steps
        if steps == 2:
            yield ModelChunk(text="Done")
            return
        assert await evaluate(tab, "window.clickedCards") == []
        image = session.scope[BrowserPerception].coordinate_source()
        assert isinstance(image, CapturedImage)
        revision = await evaluate(tab, "window.boardRevision")
        checks.remember(image, revision)
        if steps == 0:
            await evaluate(tab, "window.swapCards()")
        steps += 1
        yield ModelChunk(tool_call=ToolCall("click_at", {"x": 50, "y": 50}))

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            BrowserPerception(
                capture=ScreenshotCapture(),
                text=None,
                screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
            ),
            _BoardChecks(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(InputPacing, Choreography, ChoreographyOverlay),
    )
    async with agent.session() as session:
        checks = session.scope[_BoardChecks]
        tab = session.scope[Browser].active_tab
        await _set_up_board(tab)
        document_and_viewport = tab.document_id, tab.viewport_revision
        result = await session.run("Click the card on the left", max_steps=3)
        assert (tab.document_id, tab.viewport_revision) == document_and_viewport
        assert await evaluate(tab, "window.clickedCards") == ["B"]

    failure, started, finished = [
        event for event in result.events if isinstance(event, ACTION_EVENTS)
    ]
    assert isinstance(failure, ActionFailedEvent) and not failure.dispatched
    assert isinstance(started, ActionStartedEvent)
    assert isinstance(finished, ActionFinishedEvent)
    assert started.action_id != failure.action_id
    assert finished.action_id == started.action_id
    assert checks.checked_revisions == [1, 2]
    rejected, accepted = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert rejected.is_error and "Inspect a fresh screenshot." in rejected.text
    assert not accepted.is_error


@pytest.mark.parametrize(
    ("change", "tool", "error"),
    [
        ("state", "click", "state changed"),
        ("state", "click_at", "state changed"),
        ("layout", "click_at", "screenshot again"),
        ("layout", "drag_at", "screenshot again"),
        ("layout", "move_mouse", "screenshot again"),
        ("layout", "send_keys", None),
        ("layout", "wait", None),
    ],
)
async def test_app_generation_checks_managed_actions(site, change, tool, error):
    step = 0

    async def respond(_request):
        nonlocal step
        step += 1
        if step != 1:
            yield ModelChunk(text="Done")
            return
        observed = session.scope[BrowserPerception].snapshot
        assert observed is not None
        assert observed.generation == Generation(
            state=(tab.document_id, ("board", 0)),
            layout=((tab.viewport_revision, tab.layout_revision), 0),
        )
        assert (
            Snapshot.model_validate_json(observed.model_dump_json()).generation
            == observed.generation
        )
        setattr(app, change, 1)
        options = {
            "click_at": {"x": 50, "y": 50},
            "drag_at": {"start": {"x": 50, "y": 50}, "end": {"x": 70, "y": 60}},
            "move_mouse": {"x": 50, "y": 50},
            "send_keys": {"key": "Escape"},
            "wait": {"seconds": 0},
        }
        if tool == "click":
            card = next((el for el in observed.elements if el.name == "A"), None)
            assert card is not None
            options["click"] = {"ref": card.ref}
        yield ModelChunk(tool_call=ToolCall(tool, options[tool]))

    agent = _app_agent(site, respond)
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        app = session.scope[_App]
        await wait_for_page(tab)
        await _set_up_board(tab)
        result = await session.run("Interact with the board", max_steps=2)
        assert await evaluate(tab, "window.clickedCards") == []

    (reply,) = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert result.text == "Done"
    if error is None:
        assert not reply.is_error, reply.text
        return
    (failure,) = [
        event for event in result.events if isinstance(event, ActionFailedEvent)
    ]
    assert reply.is_error and error in reply.text
    assert not failure.dispatched


async def test_app_block_reason_reaches_readiness_and_action_receipts(site):
    step = 0

    async def respond(_request):
        nonlocal step
        step += 1
        observation = session.scope[BrowserPerception].snapshot
        assert observation is not None
        if step == 1:
            assert observation.readiness is ReadinessStatus.READY
            app.reason = "Board input is disabled by a modal"
            yield ModelChunk(tool_call=ToolCall("click_at", {"x": 50, "y": 50}))
            return
        assert observation.readiness is ReadinessStatus.BLOCKED
        assert observation.readiness_reason == app.reason
        yield ModelChunk(text="Done")

    agent = _app_agent(site, respond)
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        app = session.scope[_App]
        await _set_up_board(tab)
        result = await session.run("Interact with the board", max_steps=2)
        assert await evaluate(tab, "window.clickedCards") == []
        for report in (
            await session.scope[PageReadiness].wait(tab),
            await wait_for_page(tab, app_state=app),
        ):
            assert report.status is ReadinessStatus.BLOCKED
            assert report.reason == app.reason

    (failure,) = [
        event for event in result.events if isinstance(event, ActionFailedEvent)
    ]
    assert not failure.dispatched and app.reason in failure.reason
    assert result.text == "Done"


def _app_agent(site, respond):
    return Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            BrowserPerception(
                screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP)
            ),
            _App(),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(InputPacing, Choreography, ChoreographyOverlay),
    )


async def _set_up_board(tab):
    await evaluate(
        tab,
        """(() => {
            document.body.innerHTML = '<button id="cardA">A</button><button id="cardB">B</button>';
            const a = document.querySelector('#cardA');
            const b = document.querySelector('#cardB');
            window.boardRevision = 1;
            window.clickedCards = [];
            for (const card of [a, b]) {
                card.style.cssText = 'position:fixed;top:20px;width:80px;height:60px';
                card.onclick = () => window.clickedCards.push(card.textContent);
            }
            a.style.left = '20px';
            b.style.left = '120px';
            window.swapCards = () => {
                a.style.left = '120px';
                b.style.left = '20px';
                window.boardRevision++;
            };
        })()""",
    )


class _BoardChecks(Plugin, provides=True):
    def __init__(self) -> None:
        super().__init__()
        self._revisions: dict[str, int] = {}
        self.checked_revisions: list[int] = []

    def remember(self, image: CapturedImage, revision: int) -> None:
        self._revisions[image.id] = revision

    @hook(CheckAction)
    async def _check(self, action: CheckAction) -> None:
        assert action.kind is ActionKind.CLICK_AT
        image = action.coordinates
        assert isinstance(image, CapturedImage)
        assert action.observation is not None and action.observation.id == image.id
        observed = self._revisions[image.id]
        self.checked_revisions.append(observed)
        current = await evaluate(action.tab, "window.boardRevision")
        if observed != current:
            raise StaleElement("The board changed. Inspect a fresh screenshot.")


class _App(Plugin, provides=True):
    def __init__(self) -> None:
        super().__init__()
        self.state = 0
        self.layout = 0
        self.reason: str | None = None

    async def setup(self, scope: PluginScope) -> None:
        scope.provide(AppState, self)

    async def generation(self, _tab) -> Generation:
        return Generation(state=("board", self.state), layout=self.layout)

    async def blocked(self, _tab) -> str | None:
        return self.reason
