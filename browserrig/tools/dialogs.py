from harnessed import Inject, Plugin, ToolError, tool

from browserrig.browser.base import Browser


class DialogTools(Plugin, needs=(Browser,)):
    @tool(
        description=(
            "Accept or dismiss the active tab's JavaScript dialog, optionally answering a prompt."
        )
    )
    async def handle_dialog(
        self, accept: bool, prompt_text: str = "", *, browser: Inject[Browser]
    ) -> str:
        tab = browser.active_tab
        if tab.dialog is None:
            raise ToolError("No JavaScript dialog is open")
        # Dialogs may block an in-flight action; handling one must bypass its lock.
        await tab.handle_dialog(accept=accept, text=prompt_text)
        return "Dialog handled."
