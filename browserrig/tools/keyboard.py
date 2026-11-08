from harnessed import Plugin, ToolError
from harnessed.kernel import needs, observes

from browserrig.browser import Browser
from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool
from browserrig.input import TypedText
from browserrig.observation import BrowserPerception
from browserrig.secrets import Secrets

from .effects import Effect
from .execution import Actions


class KeyboardTools(Plugin):
    """Keyboard input to the current focus, plus typing into a DOM ref when refs exist."""

    _actions = needs(Actions)
    _browser = needs(Browser)
    _observe = needs(BrowserPerception)
    _secrets = observes(Secrets)

    @tool(
        kind=ActionKind.PRESS,
        chainable=True,
        description=(
            "Send keyboard input to the current page focus. Provide exactly one of "
            "text for literal text, or key for one character or a named key such as "
            "Escape, Enter or Tab. Use hold_control, hold_shift, hold_alt and hold_meta "
            "for shortcuts, e.g. key='a', hold_control=true selects all."
        ),
    )
    async def send_keys(
        self,
        *,
        text: str | None = None,
        key: str | None = None,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
    ) -> Effect:
        if (text is None) == (key is None):
            raise ToolError("Provide exactly one of text or key")
        if text is not None and any((hold_control, hold_shift, hold_alt, hold_meta)):
            raise ToolError("Modifier flags require key")

        if key is not None:
            await self._browser.input.keyboard.press_key(
                key,
                hold_control=hold_control,
                hold_shift=hold_shift,
                hold_alt=hold_alt,
                hold_meta=hold_meta,
            )
            return Effect("Key dispatched.")
        assert text is not None
        secrets = self._secrets
        if secrets is not None:
            entry = await secrets.prepare(text, browser=self._browser)
            if entry is not None:
                return _secret_entered(
                    await secrets.enter(entry, self._browser.input.keyboard)
                )
        return _entered(await self._browser.input.keyboard.type_text(text))

    @tool(
        kind=ActionKind.TYPE,
        chainable=True,
        description="Type exact text into a DOM ref; clear replaces its value by default.",
    )
    async def type_text(
        self,
        ref: str,
        text: str,
        clear: bool = True,
    ) -> Effect:
        tab = self._actions.tab
        await self._observe.dom_element(tab, ref)
        point = await self._actions.element_point(ref=ref)
        await self._browser.input.mouse.move_to(point)
        # Hover may reveal an overlay over the field; hit-test before focusing it.
        await self._actions.element_point(ref=ref, scroll=False)
        field = await self._observe.dom_element(tab, ref)
        secrets = self._secrets
        # Check the secrets' domains before the field is touched.
        entry = (
            await secrets.prepare(text, browser=self._browser, field=field)
            if secrets is not None
            else None
        )
        await field.focus(select_all=clear)
        if clear:
            await self._browser.input.keyboard.press_key("Backspace")
        if entry is not None and secrets is not None:
            return _secret_entered(
                await secrets.enter(entry, self._browser.input.keyboard)
            )
        return _entered(await self._browser.input.keyboard.type_text(text))


def _entered(typed: TypedText) -> Effect:
    if typed.exact:
        return Effect("Text entered.")
    return Effect(
        f"Text entered with a slip: typed {typed.entered!r} instead of "
        f"{typed.intended!r}. Check the field before continuing."
    )


def _secret_entered(exact: bool) -> Effect:
    if exact:
        return Effect("Text entered.")
    # Never echo text that surrounds a secret.
    return Effect(
        "Text entered with a slip in the text around the secret. "
        "Check the field before continuing."
    )
