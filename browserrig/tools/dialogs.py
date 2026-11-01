from harnessed import Inject, Plugin, ToolError

from browserrig.browser import Browser
from browserrig.core import ActionKind
from browserrig.core import browser_tool as tool


class DialogTools(Plugin, needs=(Browser,)):
    @tool(
        kind=ActionKind.HANDLE_DIALOG,
        description=(
            "Accept or dismiss the active tab's JavaScript dialog, optionally answering a prompt."
        ),
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
