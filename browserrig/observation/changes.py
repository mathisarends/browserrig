from .models import Element, ElementInfo, ElementRef, Offscreen, Snapshot


def decision_change(before: Snapshot, after: Snapshot, *, dom: bool = True) -> str:
    """Detect new decisions: DOM semantics or a backend's own comparison key."""
    if (before.tab_id, before.document_id, before.url) != (
        after.tab_id,
        after.document_id,
        after.url,
    ):
        return "The tab or page navigated."
    if {tab.id for tab in before.tabs} != {tab.id for tab in after.tabs}:
        return "The set of open tabs changed."
    if before.modal != after.modal or set(after.alerts) - set(before.alerts):
        return "A modal or alert appeared or changed."
    if before.cookie_banners != after.cookie_banners:
        return "A cookie banner appeared, disappeared or changed."
    if (
        not dom
        or any(
            not isinstance(el, Element) for el in (*before.elements, *after.elements)
        )
        or any(
            not isinstance(el, Offscreen)
            for el in (*before.offscreen, *after.offscreen)
        )
    ):
        return (
            "The observed content changed."
            if before.fingerprint != after.fingerprint
            else ""
        )
    return _dom_change(before, after)


def _dom_change(before: Snapshot, after: Snapshot) -> str:
    # Backend identities survive observation refreshes. Controls outside the viewport count as
    # known, so scrolling a field into view does not itself interrupt form filling.
    known: dict[tuple[str, int], ElementInfo | None] = {
        _identity(control): None for control in before.offscreen
    }
    known.update(
        (_identity(el), el)
        for el in before.elements
        if not el.covered and not el.disabled
    )
    for element in after.elements:
        if not element.in_viewport or element.covered or element.disabled:
            continue
        identity = _identity(element)
        if identity not in known:
            return "New interactive elements became available."
        previous = known[identity]
        if (
            element.expanded is True
            and previous is not None
            and previous.expanded is not True
        ):
            return "A control expanded."
    return ""


def _identity(control: ElementRef) -> tuple[str, int]:
    assert isinstance(control, (Element, Offscreen))
    return control.frame_id, control.backend_id
