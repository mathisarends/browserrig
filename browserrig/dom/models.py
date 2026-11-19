from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Self, override

from pydantic import Field

from browserrig.core import Bounds, Options
from browserrig.observation import PageContent, PagePart, Snapshot, Target

type Tristate = bool | Literal["mixed"] | None
type ViewportSide = Literal["above", "below"]
CHECKABLE_ROLES = frozenset(
    {"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"}
)


class Option(Options):
    label: str
    value: str | None = None
    selected: bool = False
    disabled: bool = False


class ScrollInfo(Options):
    """Remaining wheel-scroll distances inside a control, in CSS pixels."""

    up: float = 0
    down: float = 0
    left: float = 0
    right: float = 0


class ElementRef(Options):
    """An opaque reference owned by a capture backend within one tab and document."""

    ref: str


class ElementInfo(Target):
    """A DOM control as observed, independent of how the backend finds it again."""

    order: int = 0
    tag: str = ""
    input_type: str = ""
    value: str | None = None
    placeholder: str = ""
    description: str = ""
    href: str = ""
    options: tuple[Option, ...] = ()
    multiple: bool = False
    control_id: str = ""
    selection_group: str = ""
    section: str = ""
    group: str = ""
    outside_viewport: ViewportSide | None = None
    scroll: ScrollInfo | None = None
    covered: bool = False
    pinned: bool = False
    disabled: bool = False
    checked: Tristate = None
    selected: bool = False
    expanded: bool | None = None
    pressed: Tristate = None
    required: bool = False
    readonly: bool = False
    invalid: bool = False
    focused: bool = False
    has_popup: str = ""
    current: str = ""
    draggable: bool = False


class Element(ElementInfo):
    """A DOM target. Existing DOM refs stay valid while their node stays in its document."""

    frame_id: str
    backend_id: int
    tag: str
    # An explicitly associated rendered label, used to reveal a hidden file input.
    upload_label_ref: str | None = None


class Offscreen(ElementRef):
    """A DOM control outside the viewport, known by identity until scrolled in."""

    frame_id: str
    backend_id: int


class Heading(Options):
    level: int
    text: str
    frame_id: str
    order: int = 0
    in_viewport: bool = True
    outside_viewport: ViewportSide | None = None
    section: str = ""


class TextBlock(Options):
    """Rendered text at its reading position, without an action reference.

    Bounds use the main viewport's CSS pixels, including for embedded frames.
    """

    text: str
    frame_id: str
    order: int = 0
    bounds: Bounds | None = None
    in_viewport: bool = True
    outside_viewport: ViewportSide | None = None
    truncated: bool = False
    leading_space: bool = False
    trailing_space: bool = False
    preformatted: bool = False
    # Visible text owned by a control whose accessible name may differ.
    control: ElementRef | None = None


class ContentGroup(Options):
    """A semantic container; children retain composed-document reading order.

    ElementRef leaves address the current element index, so names, states and
    new-element markers have one source of truth.
    """

    id: str
    role: str
    name: str = ""
    bounds: Bounds | None = None
    children: tuple[ContentGroup | TextBlock | Heading | ElementRef, ...] = ()


type ContentNode = ContentGroup | TextBlock | Heading | ElementRef


class Modal(Options):
    role: str
    name: str


class CookieBanner(Options):
    """A likely visible consent UI, with the refs of its ordinary page controls."""

    name: str = ""
    text: str = ""
    refs: tuple[str, ...] = ()
    modal: bool = False


class Canvas(Options):
    """A visible canvas; its pixels have no element refs, so agents point with coordinates.

    `bounds` is the visible part in viewport CSS pixels. `ref` is set when the canvas is
    also listed as an interactive element.
    """

    frame_id: str
    bounds: Bounds
    name: str = ""
    ref: str = ""
    clipped: bool = False


class DomContent(PagePart):
    """The DOM part of a snapshot; its elements are the snapshot's targets.

    `content` is the composed reading order, None for a flat element list.
    Off-screen controls keep their identities until scrolled into view.
    """

    content: tuple[ContentNode, ...] | None = None
    offscreen: tuple[Offscreen | ElementRef, ...] = Field(default=(), repr=False)
    headings: tuple[Heading, ...] = ()
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    cookie_banners: tuple[CookieBanner, ...] = ()
    canvases: tuple[Canvas, ...] = ()

    @override
    def refs(self) -> tuple[str, ...]:
        return tuple(control.ref for control in self.offscreen)

    @override
    def labels(self) -> tuple[str, ...]:
        return tuple(heading.text for heading in self.headings)

    @override
    def fingerprint(self, targets: tuple[Target, ...]) -> str:
        fingerprint = DomFingerprint(
            text=semantic_text(self.content) if self.content is not None else (),
            elements=tuple(
                ElementFingerprint.of(target)
                for target in targets
                if isinstance(target, ElementInfo)
            ),
            alerts=self.alerts,
            modal=self.modal,
            cookie_banners=self.cookie_banners,
        )
        return fingerprint.digest()


@dataclass(frozen=True, slots=True)
class DomView:
    """A snapshot read through its DOM part, with its targets typed as DOM elements."""

    snapshot: Snapshot
    elements: tuple[ElementInfo, ...]
    part: DomContent

    @classmethod
    def of(cls, snapshot: Snapshot) -> Self:
        elements = tuple(
            target for target in snapshot.targets if isinstance(target, ElementInfo)
        )
        return cls(snapshot, elements, snapshot.part(DomContent) or DomContent())

    @property
    def url(self) -> str:
        return self.snapshot.url

    @property
    def content(self) -> tuple[ContentNode, ...] | None:
        return self.part.content

    @property
    def offscreen(self) -> tuple[Offscreen | ElementRef, ...]:
        return self.part.offscreen

    @property
    def headings(self) -> tuple[Heading, ...]:
        return self.part.headings

    @property
    def alerts(self) -> tuple[str, ...]:
        return self.part.alerts

    @property
    def modal(self) -> Modal | None:
        return self.part.modal

    @property
    def cookie_banners(self) -> tuple[CookieBanner, ...]:
        return self.part.cookie_banners

    @property
    def canvases(self) -> tuple[Canvas, ...]:
        return self.part.canvases


@dataclass(slots=True)
class Extraction:
    """What DOM extraction collected, before it becomes a snapshot's targets and part."""

    url: str
    title: str
    width: float
    height: float
    scroll_y: float
    page_height: float
    elements: tuple[ElementInfo, ...] = ()
    offscreen: tuple[ElementRef, ...] = ()
    headings: tuple[Heading, ...] = ()
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    canvases: tuple[Canvas, ...] = ()
    text: str = ""
    content: tuple[ContentNode, ...] | None = None
    limitations: tuple[str, ...] = ()
    cookie_banners: tuple[CookieBanner, ...] = ()

    def page(self, limitations: tuple[str, ...] | None = None) -> PageContent:
        """This extraction as page content: its elements become targets beside a DOM part.

        `limitations` replaces the extraction's own, for example to add frame limits.
        """
        return PageContent(
            url=self.url,
            title=self.title,
            width=self.width,
            height=self.height,
            scroll_y=self.scroll_y,
            page_height=self.page_height,
            targets=self.elements,
            parts=(
                DomContent(
                    content=self.content,
                    offscreen=self.offscreen,
                    headings=self.headings,
                    alerts=self.alerts,
                    modal=self.modal,
                    cookie_banners=self.cookie_banners,
                    canvases=self.canvases,
                ),
            ),
            text=self.text,
            limitations=tuple(
                dict.fromkeys(self.limitations if limitations is None else limitations)
            ),
        )


class ElementFingerprint(Options):
    role: str
    name: str
    options: tuple[Option, ...] = ()
    multiple: bool = False
    description: str = ""
    scroll: ScrollInfo | None = None
    in_viewport: bool = True
    value: str | None
    disabled: bool
    checked: Tristate = None
    expanded: bool | None = None
    selected: bool = False
    pressed: Tristate = None

    @classmethod
    def of(cls, element: ElementInfo) -> Self:
        return cls(
            role=element.role,
            name=element.name,
            in_viewport=element.in_viewport,
            value=element.value,
            description=element.description,
            options=element.options,
            multiple=element.multiple,
            scroll=element.scroll,
            disabled=element.disabled,
            checked=element.checked,
            expanded=element.expanded,
            selected=element.selected,
            pressed=element.pressed,
        )


class DomFingerprint(Options):
    """Typed comparison data; element refs never affect equality."""

    text: tuple[str, ...]
    elements: tuple[ElementFingerprint, ...]
    alerts: tuple[str, ...] = ()
    modal: Modal | None = None
    cookie_banners: tuple[CookieBanner, ...] = ()

    def digest(self) -> str:
        data = self.model_dump_json(exclude={"cookie_banners": {"__all__": {"refs"}}})
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


def semantic_text(nodes: tuple[ContentNode, ...]) -> tuple[str, ...]:
    """Fingerprint text and structure without backend identities or geometry."""
    parts: list[str] = []
    for node in nodes:
        match node:
            case ContentGroup():
                parts.extend((node.role, node.name, *semantic_text(node.children), "/"))
            case Heading():
                parts.extend((f"h{node.level}", node.text))
            case TextBlock():
                parts.extend((node.text, "truncated" if node.truncated else ""))
    return tuple(parts)
