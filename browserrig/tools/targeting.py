from dataclasses import dataclass, field

from harnessed import Plugin, PluginState
from harnessed.kernel import PluginScope, needs
from harnessed.tracing import traced

from browserrig.browser import Tab
from browserrig.core import (
    ActionContext,
    Bounds,
    BrowserError,
    ElementPoint,
    StaleElement,
)
from browserrig.input import Input, InputTargets
from browserrig.observation import BrowserPerception

from .execution import Actions
from .intents import TargetLocated
from .scrolling import prepare_element


@dataclass
class _Aim:
    context: PluginScope | None = None
    action_id: str = ""
    points: dict[str, tuple[float, float]] = field(default_factory=dict)


class Targeting(Plugin, slot="browserrig.targeting", provides=True):
    """Reveal, aim at and hover references within the shared action lifecycle."""

    _actions = needs(Actions)
    _correlation = needs(ActionContext)
    _input = needs(Input)
    _targets = needs(InputTargets)
    _observe = needs(BrowserPerception)
    _state = PluginState(_Aim)

    async def setup(self, scope: PluginScope) -> None:
        self._state.context = scope

    @traced
    async def locate(
        self, *, ref: str, tab: Tab | None = None, scroll: bool = True
    ) -> ElementPoint:
        """Reveal a reference and return a hit-tested, action-stable aim point."""
        await self._actions.begin_preparation()
        tab = tab if tab is not None else self._actions.tab
        tab.layout_changed()
        handle = await self._observe.element(tab, ref)
        scrolled = False
        if scroll:
            scrolled = await prepare_element(
                tab,
                handle,
                self._input.mouse,
                document_id=tab.document_id,
                report=self._actions.record_preparation,
            )
            handle = await self._observe.element(tab, ref)
        point = await handle.locate(aim=self._aim(ref, handle.element.bounds))
        context = self._state.context
        assert context is not None
        if point.bounds is not None:
            await context.dispatch(
                TargetLocated(tab, ref, point.bounds, self._correlation.action_id)
            )
        return ElementPoint(
            x=point.x, y=point.y, bounds=point.bounds, scrolled=scrolled
        )

    @traced
    async def hover(self, *, ref: str, tab: Tab | None = None) -> ElementPoint:
        """Reveal, hover and recheck a target; follow one move, then fail if unstable."""
        tab = tab if tab is not None else self._actions.tab
        document_id = tab.document_id
        point = await self.locate(ref=ref, tab=tab)
        scrolled = point.scrolled
        for _ in range(2):
            await self._require_target(tab, document_id)
            await self._input.mouse.move_to(point)
            await self._require_target(tab, document_id)
            current = await self.locate(ref=ref, tab=tab, scroll=False)
            if (current.x, current.y) == (point.x, point.y):
                return ElementPoint(
                    x=current.x, y=current.y, bounds=current.bounds, scrolled=scrolled
                )
            point = current
        raise BrowserError(
            "ELEMENT_MOVED: Target kept moving during hover; observe again"
        )

    async def _require_target(self, tab: Tab, document_id: str) -> None:
        if tab.closed:
            raise StaleElement("The focused tab changed during hover; observe again")
        await tab.sync_document()
        target = self._targets.focused()
        if tab.closed or target is None or target.id != tab.id:
            raise StaleElement("The focused tab changed during hover; observe again")
        if tab.document_id != document_id:
            raise StaleElement("The document changed during hover; observe again")

    def _aim(self, ref: str, bounds: Bounds | None) -> tuple[float, float]:
        action_id = self._correlation.action_id
        state = self._state
        if state.action_id != action_id:
            state.action_id = action_id
            state.points = {}
        aim = state.points.get(ref)
        if aim is None:
            width, height = (bounds.width, bounds.height) if bounds else (0, 0)
            aim = self._input.motor().aim_fractions(width, height)
            if action_id:
                state.points[ref] = aim
        return aim
