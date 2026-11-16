"""Remove structural context that a capture is configured to leave out."""

from dataclasses import replace

from .models import ContentGroup, ContentNode, ElementInfo, Heading, PageContent

# Page regions; dialogs stay grouped because they decide what can be operated.
_LANDMARK_ROLES = frozenset(
    {"banner", "navigation", "main", "complementary", "contentinfo", "search", "region"}
)


def outline(page: PageContent, *, headings: bool, landmarks: bool) -> PageContent:
    """`page` without headings and/or page landmarks; controls keep their order."""
    if headings and landmarks:
        return page
    kept = page.headings if headings else ()
    return replace(
        page,
        elements=page.elements
        if landmarks
        else tuple(_unsectioned(element) for element in page.elements),
        headings=kept if landmarks else tuple(_unsectioned(item) for item in kept),
        content=None
        if page.content is None
        else _nodes(page.content, headings=headings, landmarks=landmarks),
    )


def _unsectioned[T: (ElementInfo, Heading)](item: T) -> T:
    if not item.section or item.section.startswith("DIALOG"):
        return item
    return item.model_copy(update={"section": ""})


def _nodes(
    nodes: tuple[ContentNode, ...], *, headings: bool, landmarks: bool
) -> tuple[ContentNode, ...]:
    kept: list[ContentNode] = []
    for node in nodes:
        if isinstance(node, Heading) and not headings:
            continue
        if not isinstance(node, ContentGroup):
            kept.append(node)
            continue
        children = _nodes(node.children, headings=headings, landmarks=landmarks)
        if not landmarks and node.role in _LANDMARK_ROLES:
            kept.extend(children)
        elif children:
            kept.append(node.model_copy(update={"children": children}))
    return tuple(kept)
