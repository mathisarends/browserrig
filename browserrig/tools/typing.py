from functools import partial
from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import PluginScope, needs, observes
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.dom import DomElementHandle, ResolveDomElement
from browserrig.input import Keyboard
from browserrig.secrets import Secrets

from .effects import Effect
from .execution import Actions
from .parameters import log_missing_dom_refs, require_dom_resolver, supports_dom_refs
from .targeting import Targeting
from .text_entry import entered, secret_entered


class DomTypingTools(Plugin):
    """Address and verify DOM fields using the shared keyboard and motor."""

    _actions = needs(Actions)
    _targets = needs(Targeting)
    _browser = needs(Browser)
    _keyboard = needs(Keyboard)
    _elements = observes(ResolveDomElement)
    _secrets = observes(Secrets)

    async def setup(self, scope: PluginScope) -> None:
        await super().setup(scope)
        log_missing_dom_refs(scope, type(self).__name__)

    @tool(
        kind=ActionKind.TYPE,
        enabled=supports_dom_refs,
        chainable=True,
        description="Type into an observed DOM field and verify its value.",
    )
    async def type_text(
        self,
        ref: str,
        text: str,
        clear: Annotated[
            bool, Field(description="Replace the current field value before typing.")
        ] = True,
        *,
        press_enter_after: Annotated[
            bool,
            Field(
                description=(
                    "Press Enter after successful typing if the field stays focused "
                    "and the page presents no new choices."
                )
            ),
        ] = False,
    ) -> Effect:
        tab = self._actions.tab
        resolver = require_dom_resolver(self._elements)
        await resolver(tab, ref)
        await self._targets.hover(ref=ref, tab=tab)
        field = await resolver(tab, ref)
        secrets = self._secrets
        # Check the secrets' domains before the field is touched.
        entry = (
            await secrets.prepare(text, browser=self._browser, field=field)
            if secrets is not None
            else None
        )
        await field.focus(select_all=clear)
        guard = partial(_require_focus, self._browser, tab, field)
        await guard()
        before = await field.text_state()
        # Backspace on an empty token input can select/remove its preceding chip.
        if clear and (before is None or before.value):
            await self._keyboard.press_key("Backspace")
        await guard()

        typed = None
        if entry is not None and secrets is not None:
            exact = await secrets.enter(entry, self._keyboard)
            effect = secret_entered(exact)
        else:
            typed = await self._keyboard.type_text(text, guard=guard)
            effect = entered(typed)

        if (
            press_enter_after
            and not effect.break_chain
            and (change := await self._actions.page_change(after_input=False))
        ):
            return Effect(
                f"Text dispatched. {change} Enter was not pressed. Observe before continuing.",
                break_chain=True,
            )

        if typed is not None:
            after = await field.text_state()
            expected = typed.entered if clear else None
            if (
                not clear
                and before is not None
                and before.start is not None
                and before.end is not None
            ):
                expected = (
                    before.value[: before.start]
                    + typed.entered
                    + before.value[before.end :]
                )
            if after is not None and expected is not None and after.value != expected:
                effect = Effect(
                    "Text dispatched, but the field value differs. The page may have "
                    "reformatted or rejected the input. Observe the field before continuing.",
                    break_chain=True,
                )
        if not press_enter_after:
            return effect
        return await self._press_enter(tab, field, effect)

    async def _press_enter(
        self, tab: Tab, field: DomElementHandle, effect: Effect
    ) -> Effect:
        if effect.break_chain:
            return Effect(f"{effect.text} Enter was not pressed.", break_chain=True)
        if not await _has_focus(self._browser, tab, field):
            return Effect(
                f"{effect.text} The addressed field lost focus. Enter was not pressed. "
                "Observe before continuing.",
                break_chain=True,
            )
        await self._keyboard.press_key("Enter")
        return Effect(f"{effect.text} Enter pressed.", break_chain=True)


async def _require_focus(browser: Browser, tab: Tab, field: DomElementHandle) -> None:
    if not await _has_focus(browser, tab, field):
        raise BrowserError(
            "Typing stopped: the addressed field lost focus. Inspect the current "
            "focus and field value before continuing; remaining text was not sent."
        )


async def _has_focus(browser: Browser, tab: Tab, field: DomElementHandle) -> bool:
    return browser.active_tab is tab and await field.is_focused()
