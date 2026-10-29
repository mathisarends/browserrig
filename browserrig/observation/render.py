from typing import Self

import yaml

from browserrig.core.kinds import ObservationKind
from browserrig.core.options import Options
from browserrig.readiness.models import ReadinessStatus

from .models import Element, Snapshot


class PageView(Options):
    tab: str
    document: str
    url: str
    title: str
    mode: ObservationKind
    readiness: ReadinessStatus


class ViewportView(Options):
    width: float
    height: float
    scroll_y: float


class ElementView(Options):
    ref: str
    in_viewport: bool
    mark: int | None = None
    role: str
    name: str
    tag: str
    input_type: str = ""
    value: str | None = None
    disabled: bool = False
    checked: bool | None = None
    draggable: bool = False
    options: tuple[str, ...] = ()

    @classmethod
    def from_element(cls, element: Element) -> Self:
        return cls(
            ref=element.ref,
            in_viewport=element.in_viewport,
            mark=element.mark,
            role=element.role,
            name=element.name,
            tag=element.tag,
            input_type=element.input_type,
            value=element.value,
            disabled=element.disabled,
            checked=element.checked,
            draggable=element.draggable,
            options=element.options,
        )


class SnapshotView(Options):
    page: PageView
    viewport: ViewportView
    text: str | None = None
    elements: tuple[ElementView, ...] | None = None
    limitations: tuple[str, ...] | None = None

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot) -> Self:
        return cls(
            page=PageView(
                tab=snapshot.tab_id,
                document=snapshot.document_id,
                url=snapshot.url,
                title=snapshot.title,
                mode=snapshot.mode,
                readiness=snapshot.readiness,
            ),
            viewport=ViewportView(
                width=snapshot.width, height=snapshot.height, scroll_y=snapshot.scroll_y
            ),
            text=snapshot.text or None,
            elements=tuple(ElementView.from_element(element) for element in snapshot.elements)
            or None,
            limitations=snapshot.limitations or None,
        )


def render(snapshot: Snapshot) -> str:
    return yaml.safe_dump(
        SnapshotView.from_snapshot(snapshot).model_dump(
            mode="json", exclude_none=True, exclude_defaults=True
        ),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
