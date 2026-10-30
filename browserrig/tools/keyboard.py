from harnessed import Inject, Plugin, ToolError, tool

from browserrig.browser.tab import Tab
from browserrig.core.kinds import ActionKind
from browserrig.observation.plugin import Observe, has_dom_refs

from .execution import Actions, Effect


class KeyboardTools(Plugin, needs=(Actions, Observe)):
    _observe: Inject[Observe]

    @tool(
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
    ) -> str:
        async def type_text(tab: Tab) -> Effect:
            point = await actions.element_point(tab=tab, ref=ref)
            await tab.mouse.move_to(point)
            # Hover may reveal an overlay over the field; hit-test before focusing it.
            await actions.element_point(tab=tab, ref=ref, scroll=False)
            field = await self._observe.element(tab, ref)
            await field.focus(select_all=clear)
            if clear:
                await tab.keyboard.press_key("Backspace")
            await tab.keyboard.type_text(text)
            return Effect("Text entered.")

        return await actions.run(kind=ActionKind.TYPE, operation=type_text)

    @tool(
        description=(
            "Send keyboard input to the current page focus. Provide exactly one of "
            "text for literal text, or key for one character or a named key such as "
            "Escape, Enter or Tab. Use hold_control, hold_shift, hold_alt and hold_meta "
            "for shortcuts, e.g. key='a', hold_control=true selects all."
        )
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
    ) -> str:
        if (text is None) == (key is None):
            raise ToolError("Provide exactly one of text or key")
        if text is not None and any((hold_control, hold_shift, hold_alt, hold_meta)):
            raise ToolError("Modifier flags require key")

        async def send(tab: Tab) -> Effect:
            if key is not None:
                await tab.keyboard.press_key(
                    key,
                    hold_control=hold_control,
                    hold_shift=hold_shift,
                    hold_alt=hold_alt,
                    hold_meta=hold_meta,
                )
                return Effect("Key dispatched.")
            assert text is not None
            await tab.keyboard.type_text(text)
            return Effect("Text entered.")

        return await actions.run(
            kind=ActionKind.PRESS if key is not None else ActionKind.TYPE, operation=send
        )
