from harnessed import Inject, Plugin, ToolError, ToolResult

from browserrig.browser.base import Browser
from browserrig.browser.tab import Tab
from browserrig.core.kinds import ActionKind
from browserrig.core.tools import browser_tool as tool
from browserrig.observation.plugin import Observe, has_dom_refs
from browserrig.secrets import Secrets

from .execution import Actions, Effect


class DomKeyboardTools(Plugin, needs=(Actions, Browser, Observe)):
    _browser: Inject[Browser]
    _observe: Inject[Observe]

    @tool(
        kind=ActionKind.TYPE,
        chainable=True,
        enabled=has_dom_refs,
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
        async def type_text(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await self._browser.mouse.move_to(point)
            # Hover may reveal an overlay over the field; hit-test before focusing it.
            await actions.element_point(tab=tab, ref=ref, scroll=False)
            field = await self._observe.element(tab, ref)
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
                await secrets.enter(entry, self._browser.keyboard)
            else:
                await self._browser.keyboard.type_text(text)
            return Effect("Text entered.")

        return await actions.run(kind=ActionKind.TYPE, operation=type_text)


class KeyboardTools(Plugin, needs=(Actions, Browser, Observe)):
    """Keyboard input to the current focus, independent of DOM references."""

    _browser: Inject[Browser]

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
        text: str | None = None,
        key: str | None = None,
        hold_control: bool = False,
        hold_shift: bool = False,
        hold_alt: bool = False,
        hold_meta: bool = False,
        *,
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
                    await secrets.enter(entry, self._browser.keyboard)
                    return Effect("Text entered.")
            await self._browser.keyboard.type_text(text)
            return Effect("Text entered.")

        return await actions.run(kind=ActionKind.PRESS, operation=send)
