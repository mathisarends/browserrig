from harnessed import Inject, Plugin, tool

from browserrig.browser.errors import BrowserError
from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind, ElementOperation

from .execution import Actions, Effect

_FOCUSED_EDITOR = """(() => {
    let el = document.activeElement;
    while (el) {
        if (el.shadowRoot?.activeElement) { el = el.shadowRoot.activeElement; continue; }
        if (el.localName === 'iframe') {
            try {
                if (!el.contentDocument) { return {editable: true, sensitive: true}; }
                el = el.contentDocument.activeElement; continue;
            } catch { return {editable: true, sensitive: true}; }
        }
        return {editable: !el.disabled && !el.readOnly &&
            (el.matches('input,textarea') || el.isContentEditable),
            sensitive: el.type === 'password' || el.localName.includes('-')};
    }
    return {editable: false, sensitive: true};
})()"""


class KeyboardTools(Plugin):
    @tool(description="Press a page key, optionally with modifiers, e.g. Enter, Tab or Control+a.")
    async def press_key(self, key: str, *, actions: Inject[Actions]) -> str:
        async def press(tab: Tab) -> Effect:
            editor = await tab.evaluate(_FOCUSED_EDITOR)
            await tab.input.press_key(key, sensitive=editor["sensitive"])
            return Effect("Key dispatched.")

        return await actions.run(kind=ActionKind.PRESS, operation=press)

    @tool(
        description=(
            "Type exact text into a DOM ref or the focused editor in canvas mode. "
            "With a ref, clear defaults to true; without a ref, it defaults to false. "
            "Set sensitive for private input; password fields are automatically masked."
        )
    )
    async def type_text(
        self,
        text: str,
        ref: str | None = None,
        clear: bool | None = None,
        sensitive: bool = False,
        *,
        actions: Inject[Actions],
    ) -> str:
        async def type_text(tab: Tab) -> Effect:
            replace = ref is not None if clear is None else clear
            if ref is not None:
                point = await actions.element_point(tab=tab, ref=ref)
                await tab.input.move_to(point)
                await actions.element_point(tab=tab, ref=ref, scroll=False)
                await actions.element_call(
                    tab=tab, ref=ref, operation=ElementOperation.FOCUS, value=replace
                )
                _, element = await actions.observe.element(tab, ref)
                private = sensitive or element.input_type == "password"
            else:
                editor = await tab.evaluate(_FOCUSED_EDITOR)
                if not editor["editable"]:
                    raise BrowserError("Focus an editable field before typing without a ref")
                private = sensitive or editor["sensitive"]
                if replace:
                    await tab.input.select_all(sensitive=private)
            if replace:
                await tab.input.press_key("Backspace", sensitive=private)
            await tab.input.type_text(text, sensitive=private)
            return Effect("Text entered.")

        return await actions.run(kind=ActionKind.TYPE, operation=type_text)
