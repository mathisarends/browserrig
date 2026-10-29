from harnessed import Inject, Plugin, ToolError, tool

from browserrig.browser.base import Browser


class DialogTools(Plugin):
    @tool(
        description=(
            "Accept or dismiss the active tab's JavaScript dialog, optionally answering a prompt."
        )
    )
    async def handle_dialog(
        self, accept: bool, prompt_text: str = "", *, browser: Inject[Browser]
    ) -> str:
        """Accept or dismiss the active tab's JavaScript dialog, optionally answering a prompt."""
        tab = browser.active_tab
        if tab.dialog is None:
            raise ToolError("No JavaScript dialog is open")
        await tab.cdp.page.handle_java_script_dialog(accept=accept, prompt_text=prompt_text)
        return "Dialog handled."
