from browserrig.observation.models import CHECKABLE_ROLES, ElementInfo, Option

from .text import cut, format_link, quote

_PLAIN_TYPES = frozenset(
    {"", "text", "checkbox", "radio", "submit", "button", "search"}
)


_FLAGS = ("required", "readonly", "invalid", "focused", "draggable", "multiple")


_MAX_NAME = 100


_MAX_OPTIONS = 10


def render_element(element: ElementInfo, url: str) -> str:
    role = element.role if element.role and element.role != "generic" else element.tag
    parts = [f"{'*' if element.new else ''}[{element.ref}] {role}"]
    if element.input_type not in _PLAIN_TYPES:
        parts[0] += f"[type={element.input_type}]"
    if element.name:
        parts.append(quote(element.name, _MAX_NAME))
    if element.scroll is not None:
        directions = [
            f"{direction}={distance:.0f}px"
            for direction in ("up", "down", "left", "right")
            if (distance := getattr(element.scroll, direction)) > 1
        ]
        parts.append(f"scroll({', '.join(directions)})")
    parts.extend(_states(element))
    if element.value is not None and element.value != element.name:
        parts.append(f"value={quote(element.value, 100)}")
    if (
        element.placeholder
        and element.placeholder != element.name
        and not element.value
    ):
        parts.append(f"placeholder={quote(element.placeholder, 60)}")
    if element.control_id:
        parts.append(f"id={quote(element.control_id, 100)}")
    if element.selection_group:
        parts.append(f"selection_group={quote(element.selection_group, 100)}")
    if element.options:
        shown = [_option(option) for option in element.options[:_MAX_OPTIONS]]
        if len(element.options) > _MAX_OPTIONS:
            shown.append(f"…+{len(element.options) - _MAX_OPTIONS}")
        parts.append(f"options=[{', '.join(shown)}]")
    if element.description and element.description != element.name:
        parts.append(f"description={quote(element.description, 250)}")
    link = format_link(element.href, url, element.name)
    if link:
        parts.append(f"-> {link}")
    elif not element.name and element.bounds is not None and element.value is None:
        # Without a name, size and place are what tell icons, tiles and wrappers apart.
        bounds = element.bounds
        parts.append(
            f"x={bounds.x:.0f} y={bounds.y:.0f} {bounds.width:.0f}x{bounds.height:.0f}"
        )
    return " ".join(parts)


def _option(option: Option) -> str:
    text = cut(option.label, 40)
    if option.value is not None and option.value != option.label:
        text += f" value={quote(option.value, 40)}"
    return (
        text
        + ("*" if option.selected else "")
        + (" (disabled)" if option.disabled else "")
    )


def _states(element: ElementInfo) -> list[str]:
    unchecked = "unchecked" if element.role in CHECKABLE_ROLES else ""
    current = element.current
    if current == "true":
        current = "current"
    elif current:
        current = f"current={current}"
    states = [
        "disabled" if element.disabled else "",
        _tristate(element.checked, "checked", unchecked, "mixed"),
        "selected" if element.selected else "",
        _tristate(element.pressed, "pressed", "", "pressed=mixed"),
        _tristate(element.expanded, "expanded", "collapsed", ""),
        f"haspopup={element.has_popup}" if element.has_popup else "",
        current,
        *(flag for flag in _FLAGS if getattr(element, flag)),
    ]
    return [state for state in states if state]


def _tristate(value: object, on: str, off: str, mixed: str) -> str:
    if value == "mixed":
        return mixed
    if value is True:
        return on
    return off if value is False else ""
