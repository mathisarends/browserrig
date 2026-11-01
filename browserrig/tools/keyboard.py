from harnessed import Inject, Plugin, ToolError, ToolResult
from harnessed.kernel import dependency

from browserrig.browser import Browser, Tab
from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool
from browserrig.input import TypedText
from browserrig.observation import Observe
from browserrig.secrets import Secrets

from .effects import Effect
from .execution import Actions


class KeyboardTools(Plugin, needs=(Actions,)):
    """Keyboard input to the current focus, plus typing into a DOM ref when refs exist."""

    _browser = dependency(Browser)
    _observe = dependency(Observe)

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
        actions: Inject[Actions],
        secrets: Inject[Secrets | None] = None,
    ) -> ToolResult:
        if (text is None) == (key is None):
            raise ToolError("Provide exactly one of text or key")
        if text is not None and any((hold_control, hold_shift, hold_alt, hold_meta)):
            raise ToolError("Modifier flags require key")

        async def send(_tab: Tab) -> Effect:
            if key is not None:
                await self._browser.keyboard.press_key(
                    key,
                    hold_control=hold_control,
                    hold_shift=hold_shift,
                    hold_alt=hold_alt,
                    hold_meta=hold_meta,
                )
                return Effect("Key dispatched.")
            assert text is not None
            if secrets is not None:
                entry = await secrets.prepare(text, browser=self._browser)
                if entry is not None:
                    return _secret_entered(
                        await secrets.enter(entry, self._browser.keyboard)
                    )
            return _entered(await self._browser.keyboard.type_text(text))

        return await actions.run(kind=ActionKind.PRESS, operation=send)

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
        *,
        actions: Inject[Actions],
        secrets: Inject[Secrets | None] = None,
    ) -> ToolResult:
        async def check(tab: Tab) -> None:
            await self._observe.dom_element(tab, ref)

        async def type_text(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await self._browser.mouse.move_to(point)
            # Hover may reveal an overlay over the field; hit-test before focusing it.
            await actions.element_point(tab=tab, ref=ref, scroll=False)
            field = await self._observe.dom_element(tab, ref)
            # Check the secrets' domains before the field is touched.
            entry = (
                await secrets.prepare(text, browser=self._browser, field=field)
                if secrets is not None
                else None
            )
            await field.focus(select_all=clear)
            if clear:
                await self._browser.keyboard.press_key("Backspace")
            if entry is not None and secrets is not None:
                return _secret_entered(
                    await secrets.enter(entry, self._browser.keyboard)
                )
            return _entered(await self._browser.keyboard.type_text(text))

        return await actions.run(kind=ActionKind.TYPE, operation=type_text, check=check)


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
