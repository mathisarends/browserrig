"""Render mixed page content without losing the position of noninteractive text."""

from collections.abc import Callable
from typing import Literal

from .models import (
    ContentGroup,
    ContentNode,
    CookieBanner,
    ElementInfo,
    ElementRef,
    Heading,
    Snapshot,
    TextBlock,
)

_LANDMARKS = {
    "banner": "HEADER",
    "navigation": "NAVIGATION",
    "main": "MAIN",
    "complementary": "SIDEBAR",
    "contentinfo": "FOOTER",
    "search": "SEARCH",
    "region": "SECTION",
    "dialog": "DIALOG",
    "alertdialog": "DIALOG",
}
_TRANSPARENT = frozenset({"paragraph", "preformatted", "blockquote"})
_PROSE = frozenset({"paragraph", "blockquote", "listitem", "cell"})


def render_flow(
    snapshot: Snapshot,
    position: Literal["above", "below"] | None,
    format_element: Callable[[ElementInfo], str],
) -> list[str]:
    """Filter leaves to one viewport partition while retaining their enclosing groups."""
    elements = {element.ref: element for element in snapshot.elements}
    nodes = _partition(snapshot.content or (), elements, position)
    banners = _banners(nodes, snapshot.cookie_banners) if position is None else {}
    lines: list[str] = []
    for banner in snapshot.cookie_banners:
        if position is None and banner not in banners.values():
            lines.extend(_banner(banner, 1))
    lines.extend(_lines(nodes, elements, format_element, banners, 1))
    return lines


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


def _partition(
    nodes: tuple[ContentNode, ...],
    elements: dict[str, ElementInfo],
    position: Literal["above", "below"] | None,
) -> tuple[ContentNode, ...]:
    selected: list[ContentNode] = []
    for node in nodes:
        if isinstance(node, ContentGroup):
            children = _partition(node.children, elements, position)
            if children:
                selected.append(node.model_copy(update={"children": children}))
            continue
        leaf = elements.get(node.ref) if isinstance(node, ElementRef) else node
        if leaf is None:
            continue
        visible = (
            leaf.in_viewport
            if position is None
            else (not leaf.in_viewport and leaf.outside_viewport == position)
        )
        if visible and not (isinstance(leaf, ElementInfo) and leaf.covered):
            selected.append(node)
    return tuple(selected)


def _banners(
    nodes: tuple[ContentNode, ...], banners: tuple[CookieBanner, ...]
) -> dict[str, CookieBanner]:
    found: dict[str, CookieBanner] = {}
    for node in nodes:
        if not isinstance(node, ContentGroup):
            continue
        nested = _banners(node.children, banners)
        found.update(nested)
        refs = _refs(node.children)
        for banner in banners:
            wanted = set(banner.refs)
            if wanted and wanted <= refs and banner not in found.values():
                found[node.id] = banner
    return found


def _refs(nodes: tuple[ContentNode, ...]) -> set[str]:
    refs: set[str] = set()
    for node in nodes:
        if isinstance(node, ContentGroup):
            refs.update(_refs(node.children))
        elif isinstance(node, ElementRef):
            refs.add(node.ref)
    return refs


def _lines(
    nodes: tuple[ContentNode, ...],
    elements: dict[str, ElementInfo],
    format_element: Callable[[ElementInfo], str],
    banners: dict[str, CookieBanner],
    depth: int,
    *,
    banner_text: bool = False,
) -> list[str]:
    lines: list[str] = []
    skip = False
    for index, node in enumerate(nodes):
        if skip:
            skip = False
            continue
        indent = "  " * depth
        match node:
            case ContentGroup():
                lines.extend(
                    _group_lines(
                        node,
                        elements,
                        format_element,
                        banners,
                        depth,
                        banner_text=banner_text,
                    )
                )
            case TextBlock():
                if not banner_text:
                    suffix = " … [text truncated]" if node.truncated else ""
                    if node.preformatted:
                        lines.append(f"{indent}text: |")
                        lines.extend(
                            f"{indent}  {line}" for line in node.text.splitlines()
                        )
                        if suffix:
                            lines.append(indent + suffix.strip())
                    else:
                        lines.append(f"{indent}text: {node.text}{suffix}")
            case Heading():
                following = nodes[index + 1] if index + 1 < len(nodes) else None
                target = (
                    elements.get(following.ref)
                    if isinstance(following, ElementRef)
                    else None
                )
                prefix = "#" * min(node.level, 6)
                if target is not None and target.name == node.text:
                    lines.append(f"{indent}{prefix} {format_element(target)}")
                    skip = True
                else:
                    lines.append(f"{indent}{prefix} {node.text}")
            case ElementRef():
                lines.append(indent + format_element(elements[node.ref]))
    return lines


def _group_lines(
    node: ContentGroup,
    elements: dict[str, ElementInfo],
    format_element: Callable[[ElementInfo], str],
    banners: dict[str, CookieBanner],
    depth: int,
    *,
    banner_text: bool,
) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    banner = banners.get(node.id)
    transparent = node.role in _TRANSPARENT
    if banner is not None:
        lines.extend(_banner(banner, depth))
    elif not transparent:
        lines.append(indent + _group(node))
    prose = _prose(node.children, elements) if node.role in _PROSE else None
    if prose is not None and not banner_text and banner is None:
        child_indent = indent if transparent else indent + "  "
        lines.append(f"{child_indent}text: {prose}")
        return lines
    lines.extend(
        _lines(
            node.children,
            elements,
            format_element,
            banners,
            depth if transparent else depth + 1,
            banner_text=banner_text or banner is not None,
        )
    )
    return lines


def _prose(
    nodes: tuple[ContentNode, ...], elements: dict[str, ElementInfo]
) -> str | None:
    if not any(isinstance(node, TextBlock) and not node.preformatted for node in nodes):
        return None
    if any(
        not isinstance(node, (TextBlock, ElementRef))
        or isinstance(node, TextBlock)
        and node.preformatted
        or isinstance(node, ElementRef)
        and (
            elements[node.ref].role != "link"
            or elements[node.ref].disabled
            or elements[node.ref].focused
            or elements[node.ref].expanded is not None
            or bool(elements[node.ref].has_popup or elements[node.ref].current)
        )
        for node in nodes
    ):
        return None
    parts: list[str] = []
    refs = {node.ref for node in nodes if isinstance(node, ElementRef)}
    visible_labels: dict[str, list[str]] = {}
    for node in nodes:
        if (
            isinstance(node, TextBlock)
            and node.control is not None
            and node.control.ref in refs
        ):
            value = node.text + (" … [text truncated]" if node.truncated else "")
            visible_labels.setdefault(node.control.ref, []).append(value)
    previous: ContentNode | None = None
    for node in nodes:
        if isinstance(node, TextBlock):
            if node.control is not None and node.control.ref in visible_labels:
                continue
            space = node.leading_space or isinstance(previous, TextBlock)
            value = node.text + (" … [text truncated]" if node.truncated else "")
        else:
            assert isinstance(node, ElementRef)
            element = elements[node.ref]
            name = " ".join(visible_labels.get(node.ref, ())) or element.name
            label = name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            value = f"{'*' if element.new else ''}[{label or 'link'}][{element.ref}]"
            space = previous.trailing_space if isinstance(previous, TextBlock) else True
        if space and parts:
            parts.append(" ")
        parts.append(value)
        previous = node
    return "".join(parts).strip()


def _group(group: ContentGroup) -> str:
    name = group.name.replace('"', "'")
    landmark = _LANDMARKS.get(group.role)
    if landmark:
        return f"[{landmark}{': ' + name if name else ''}]"
    suffix = f' "{name}"' if name else ""
    return f"<{group.role}{suffix}>"


def _banner(banner: CookieBanner, depth: int) -> list[str]:
    indent = "  " * depth
    name = f": {banner.name}" if banner.name else ""
    lines = [f"{indent}[COOKIE BANNER{name}]"]
    if banner.text:
        lines.append(f'{indent}  text: "{banner.text}"')
    return lines
