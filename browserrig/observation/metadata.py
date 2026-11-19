from typing import override

from browserrig.browser import Tab

from .capture import PageCapture, PageModel
from .models import PageContent, Snapshot
from .page_header import header
from .request import CaptureRequest


class MetadataPage(PageModel):
    """Report page and viewport facts without inspecting page elements.

    BrowserPerception uses it while no plugin supplies a page model.
    """

    @override
    async def collect(self, tab: Tab, request: CaptureRequest) -> PageCapture:
        del request
        layout = await tab.page_layout()
        size = layout.viewport
        page = PageContent(
            url=tab.url,
            title=tab.title,
            width=size.width,
            height=size.height,
            scroll_y=layout.scroll_y,
            page_height=layout.page_height,
        )
        return PageCapture(page)

    @override
    def render(self, snapshot: Snapshot) -> str:
        return "\n".join(header(snapshot, metadata_only=True))
