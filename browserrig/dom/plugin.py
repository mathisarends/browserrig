from harnessed import Instructions, Plugin, SystemPrompt
from harnessed.kernel import PluginScope, needs

from browserrig.browser import Tab
from browserrig.core import BrowserError
from browserrig.observation import BrowserPerception

from .handle import DomElementHandle
from .model import DomModel, PageProse

_FORMAT = (
    "After the header, observations list interactive elements one per line as "
    '`[ref] role "name" states value=... -> link`. Landmarks such as [MAIN] and groups '
    'like <form "Login"> may organize the controls. '
    "A leading * marks elements new since the previous observation. "
    "Inside iframes, above/below previews refer to the frame's viewport. "
    "An element with scroll(up=..., down=...) is an inner scroll container. "
    "Multiple marks multi-select controls. Options show * for selected entries "
    "and explicit values when available. Radio IDs, values and selection_group "
    "are raw page metadata. Modal dialogs can block controls outside them. "
    "Cookie banner detection is heuristic. Choose whether to interact or navigate. "
    "Canvas content has no DOM refs."
)
_PROSE = (
    " When visible prose is included, it appears in reading order beside its controls. "
    "Plain text has no action refs. Links in prose use [label][ref]."
)
_REFS = (
    "The ref is the value inside the brackets, such as 482 or f1:93. "
    "Refs stay valid while the element stays in the same document and tab, "
    "even across observations."
)


class DomPage(Plugin, slot="browserrig.page-model"):
    """Read pages from the DOM: controls with refs, visible prose, headings and landmarks.

    Supplies BrowserPerception's page model and ResolveDomElement for DOM tools.
    """

    _perception = needs(BrowserPerception)

    def __init__(
        self,
        *,
        prose: PageProse = "inline",
        max_text_chars: int = 3000,
        headings: bool = True,
        landmarks: bool = True,
        max_elements: int | None = None,
        viewport_expansion: int = 1000,
    ) -> None:
        """`prose` interleaves visible text with controls ("inline"), adds it only when the
        viewport shows few named controls ("sparse") or omits it ("off")."""
        super().__init__()
        self.model = DomModel(
            prose=prose,
            max_text_chars=max_text_chars,
            headings=headings,
            landmarks=landmarks,
            max_elements=max_elements,
            viewport_expansion=viewport_expansion,
        )

    async def setup(self, scope: PluginScope) -> None:
        perception = self._perception
        scope.effect(perception.use_model(self.model))
        scope.provide(ResolveDomElement, ResolveDomElement(perception))

    def instructions(self) -> SystemPrompt:
        text = _FORMAT + (_PROSE if self.model.prose != "off" else "")
        return SystemPrompt(
            Instructions(title="Page elements", text=text),
            Instructions(title="Element references", text=_REFS),
        )


class ResolveDomElement:
    """Resolve a DOM handle from an observation read by DomPage."""

    def __init__(self, perception: BrowserPerception) -> None:
        self._perception = perception

    async def __call__(self, tab: Tab, ref: str) -> DomElementHandle:
        handle = await self._perception.target(tab, ref)
        if not isinstance(handle, DomElementHandle):
            raise BrowserError(
                "This tool requires a DOM element; use pointer and keyboard tools"
            )
        return handle
