from functools import partial
from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import PluginScope, needs, observes
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.dom import DomElementHandle, ResolveDomElement
from browserrig.input import Input
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
    _input = needs(Input)
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
            await self._input.keyboard.press_key("Backspace")
        await guard()
        if entry is not None and secrets is not None:
            exact = await secrets.enter(entry, self._input.keyboard)
            return secret_entered(exact)
        typed = await self._input.keyboard.type_text(text, guard=guard)
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
            return Effect(
                "Text dispatched, but the field value differs. The page may have "
                "reformatted or rejected the input. Observe the field before continuing.",
                break_chain=True,
            )
        return entered(typed)


async def _require_focus(browser: Browser, tab: Tab, field: DomElementHandle) -> None:
    if browser.active_tab is not tab or not await field.is_focused():
        raise BrowserError(
            "Typing stopped: the addressed field lost focus. Inspect the current "
            "focus and field value before continuing; remaining text was not sent."
        )
