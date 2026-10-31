"""Parse rendered browser observations in tests, the way a model reads them."""

import re

from harnessed.models import ImagePart, ImageReference

_ELEMENT = re.compile(
    r'^\s*(?P<new>\*?)\[(?P<ref>[^\]]+)\] (?P<role>[^\s\[]+)\S*(?: "(?P<name>[^"]*)")?'
)
_TAB = re.compile(r"^\s*\*(?P<id>\S+)")


def is_observation(text: str) -> bool:
    return text.startswith("# ") and "\nurl: " in text


def parse(text: str) -> dict:
    """Page fields plus `elements` with ref, role, name, new and in_viewport."""
    lines = text.splitlines()
    page = {"title": lines[0].removeprefix("# "), "readiness": "ready"}
    state: dict = {"page": page, "elements": [], "notes": []}
    block = ""
    for line in lines[1:]:
        if line.startswith("note: "):
            state["notes"].append(line.removeprefix("note: "))
            continue
        if block == "page text":
            state["text"] += line + "\n"
            continue
        if not line.startswith(" "):
            block = line.split(":", 1)[0]
            key, _, value = line.partition(": ")
            if key in ("url", "tab", "readiness"):
                page[key] = value
            if line == "page text:":
                state["text"] = ""
            continue
        if block == "tabs (* = this tab)":
            match = _TAB.match(line)
            if match:
                page["tab"] = match["id"]
            continue
        match = _ELEMENT.match(line)
        if match:
            state["elements"].append(
                {
                    "ref": match["ref"],
                    "role": match["role"],
                    "name": match["name"] or "",
                    "new": bool(match["new"]),
                    "in_viewport": block == "in viewport",
                }
            )
    return state


def latest(messages) -> dict | None:
    return next(
        (
            parse(message.text)
            for message in reversed(messages)
            if is_observation(message.text)
        ),
        None,
    )


def all_states(messages) -> list[dict]:
    return [parse(message.text) for message in messages if is_observation(message.text)]


def has_image(message) -> bool:
    return not isinstance(message.content, str) and any(
        isinstance(part, ImagePart | ImageReference) for part in message.content
    )


def image_id(message) -> str:
    return next(
        line.split(";", 1)[0].removeprefix("Screenshot ")
        for line in message.text.splitlines()
        if line.startswith("Screenshot ")
    )
