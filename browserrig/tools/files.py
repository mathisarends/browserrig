from typing import Annotated

from harnessed import Inject, Plugin, tool
from pydantic import Field

from browserrig.browser.models import Download
from browserrig.browser.tab import Tab
from browserrig.kinds import ActionKind, ElementOperation

from .execution import Actions, Effect


class FileTools(Plugin, needs=(Actions,)):
    @tool
    async def upload_files(
        self,
        ref: str,
        paths: Annotated[list[str], Field(min_length=1)],
        *,
        actions: Inject[Actions],
    ) -> str:
        """Set a file input using absolute paths on the browser host, not the client host."""

        async def upload(tab: Tab) -> Effect:
            frame, element = await actions.observe.element(tab, ref)
            if element.input_type != "file":
                raise ValueError("Target is not a file input")
            node = await actions.element_call(
                tab=tab, ref=ref, operation=ElementOperation.NODE, by_value=False
            )
            try:
                await frame.cdp.dom.set_file_input_files(files=paths, object_id=node.object_id)
            finally:
                await frame.cdp.runtime.release_object(object_id=node.object_id)
            return Effect("Files assigned to input.")

        return await actions.run(
            kind=ActionKind.UPLOAD,
            operation=upload,
        )

    @tool(readonly=True)
    async def list_downloads(self, *, actions: Inject[Actions]) -> tuple[Download, ...]:
        """List download status and browser-host paths, when configured by the host."""
        return await actions.browser.downloads()
