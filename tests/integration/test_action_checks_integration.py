import pytest
from harnessed import Plugin, PolicyDecision, ToolCall, hook
from harnessed.events import ToolCallFinishedEvent
from harnessed.kernel import needs
from harnessed.models import ModelChunk
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    ActionKind,
    Agent,
    Browser,
    BrowserPerception,
    Choreography,
    ChoreographyOverlay,
    Chrome,
    InputPacing,
    ScreenshotCapture,
    Screenshots,
    ScreenshotTrigger,
)
from browserrig.core import StaleElement
from browserrig.events import (
    ACTION_EVENTS,
    ActionFailedEvent,
    ActionFinishedEvent,
    ActionStartedEvent,
)
from browserrig.observation import CapturedImage
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
    _perception = needs(BrowserPerception)

    def __init__(self) -> None:
        super().__init__()
        self._revisions: dict[str, int] = {}
        self.checked_revisions: list[int] = []

    def remember(self, image: CapturedImage, revision: int) -> None:
        self._revisions[image.id] = revision

    @hook(CheckAction)
    async def _check(self, action: CheckAction) -> None:
        assert action.kind is ActionKind.CLICK_AT
        image = self._perception.coordinate_source()
        assert isinstance(image, CapturedImage)
        observed = self._revisions[image.id]
        self.checked_revisions.append(observed)
        current = await evaluate(action.tab, "window.boardRevision")
        if observed != current:
            raise StaleElement("The board changed. Inspect a fresh screenshot.")
