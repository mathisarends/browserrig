from functools import partial
from typing import Annotated

from harnessed import Plugin
from harnessed.kernel import needs, observes
from pydantic import Field

from browserrig.browser import Browser, Tab
from browserrig.core import ActionKind, BrowserError
from browserrig.core import browser_tool as tool
from browserrig.input import Input, TypedText
from browserrig.observation import DomElementHandle, DomElements
from browserrig.secrets import Secrets

from .effects import Effect
from .execution import Actions
from .targeting import Targeting


class DomTypingTools(Plugin):
    """Address and verify DOM fields using the shared keyboard and motor."""

    _actions = needs(Actions)
    _targets = needs(Targeting)
    _browser = needs(Browser)
    _input = needs(Input)
    _elements = needs(DomElements)
    _secrets = observes(Secrets)

    @tool(
        kind=ActionKind.TYPE,
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
        await self._elements.resolve(tab, ref)
        await self._targets.hover(ref=ref, tab=tab)
        field = await self._elements.resolve(tab, ref)
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
            return _secret_entered(await secrets.enter(entry, self._input.keyboard))
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
        return _entered(typed)


async def _require_focus(browser: Browser, tab: Tab, field: DomElementHandle) -> None:
    if browser.active_tab is not tab or not await field.is_focused():
        raise BrowserError(
            "Typing stopped: the addressed field lost focus. Inspect the current "
            "focus and field value before continuing; remaining text was not sent."
        )


def _entered(typed: TypedText) -> Effect:
    if typed.exact:
        return Effect("Text entered.")
    return Effect(
        f"Text entered with a slip: typed {typed.entered!r} instead of "
        f"{typed.intended!r}. Check the field before continuing.",
        break_chain=True,
    )


def _secret_entered(exact: bool) -> Effect:
    if exact:
        return Effect("Text entered.")
    # Never echo text that surrounds a secret.
    return Effect(
        "Text entered with a slip in the text around the secret. "
        "Check the field before continuing.",
        break_chain=True,
    )
