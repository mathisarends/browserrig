from harnessed.kernel import Scope

from browserrig.browser import Browser, Tab
from browserrig.core import Bounds, ElementPoint, traced
from browserrig.observation import BrowserPerception

from .intents import TargetLocated
from .scrolling import prepare_element


class Targeting:
    """Reveal refs and keep the motor's aim stable throughout one action."""

    def __init__(
        self, browser: Browser, observe: BrowserPerception, context: Scope
    ) -> None:
        self.browser = browser
        self.observe = observe
        self._context = context
        self._aim_action = ""
        self._aims: dict[str, tuple[float, float]] = {}

    @traced
    async def locate(self, *, tab: Tab, ref: str, scroll: bool = True) -> ElementPoint:
        """Reveal a ref with wheel input, then return a hit-tested point.

        The point is where the motor aims on the target, unless something covers that
        spot. Plugins learn about the target through `TargetLocated`.

        Use `scroll=False` to re-check the target after hover or other input moved it.
        """
        handle = await self.observe.element(tab, ref)
        scrolled = False
        if scroll:
            scrolled = await prepare_element(
                tab, handle, self.browser.mouse, document_id=tab.document_id
            )
            # Wheel input may have moved ancestor documents; refresh their transforms.
            handle = await self.observe.element(tab, ref)
        point = await handle.locate(aim=self._aim(ref, handle.element.bounds))
        if point.bounds is not None:
            await self._context.dispatch(
                TargetLocated(tab, ref, point.bounds, self.browser.input.action_id)
            )
        return ElementPoint(
            x=point.x, y=point.y, bounds=point.bounds, scrolled=scrolled
        )

    def _aim(self, ref: str, bounds: Bounds | None) -> tuple[float, float]:
        """The motor's spot on `ref`, chosen once per action."""
        action_id = self.browser.input.action_id
        if self._aim_action != action_id:
            self._aim_action = action_id
            self._aims = {}
        aim = self._aims.get(ref)
        if aim is None:
            width, height = (bounds.width, bounds.height) if bounds else (0, 0)
            motor = self.browser.input.motor()
            aim = motor.aim_fractions(width, height)
            if action_id:
                self._aims[ref] = aim
        return aim
