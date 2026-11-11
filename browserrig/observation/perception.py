from harnessed.kernel import PluginScope

from browserrig.browser import Tab
from browserrig.core import BrowserError

from .config import Screenshots
from .dom_capture import DomCapture
from .handle import DomElementHandle
from .plugin import BrowserPerception
from .renderer import DomRenderer, Renderer


class DomPerception(BrowserPerception, provides=BrowserPerception):
    """DOM observation backend, without model tools or context-history policy."""

    def __init__(
        self,
        *,
        capture: DomCapture | None = None,
        renderer: Renderer | None = None,
        screenshots: Screenshots | None = None,
    ) -> None:
        capture = capture if capture is not None else DomCapture()
        super().__init__(
            capture=capture,
            renderer=renderer
            if renderer is not None
            else DomRenderer(
                max_text_chars=capture.max_text_chars,
                sparse_text_chars=capture.sparse_text_chars,
                marks=capture.marks,
            ),
            screenshots=screenshots,
        )

    async def setup(self, scope: PluginScope) -> None:
        await super().setup(scope)
        scope.provide(DomElements, DomElements(self))


class DomElements:
    """Typed access to DOM handles from the current published reference set."""

    def __init__(self, perception: BrowserPerception) -> None:
        self._perception = perception

    async def resolve(self, tab: Tab, ref: str) -> DomElementHandle:
        handle = await self._perception.element(tab, ref)
        if not isinstance(handle, DomElementHandle):
            raise BrowserError(
                "This tool requires a DOM element; use pointer and keyboard tools"
            )
        return handle
