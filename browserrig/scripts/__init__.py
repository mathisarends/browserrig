"""Load and validate the standalone scripts sent to the isolated CDP world."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .models import (
    ContentArgs,
    ContentExtraction,
    CursorArgs,
    DOMProbe,
    ElementArgs,
    FindArgs,
    FindResult,
    OwnerHitsArgs,
    OwnerScrollArgs,
    PageFacts,
    ScriptArgs,
    ScrollArgs,
    ScrollPlan,
    SecretField,
    SecretFieldArgs,
    SecretFocus,
    SecretFocusArgs,
    SeedArgs,
    TabStrip,
)


class ScriptError(StrEnum):
    STALE_ELEMENT = "STALE_ELEMENT"
    ELEMENT_BLOCKED = "ELEMENT_BLOCKED"
    ELEMENT_DISABLED = "ELEMENT_DISABLED"
    NOT_EDITABLE = "NOT_EDITABLE"
    OPTION_NOT_FOUND = "OPTION_NOT_FOUND"
    NOT_A_SELECT = "NOT_A_SELECT"
    INVALID_VALUE = "INVALID_VALUE"


@dataclass(frozen=True, slots=True)
class Script[A: BaseModel, R]:
    name: str
    declaration: str
    arguments: type[A]
    parse: Callable[[Any], R]

    @classmethod
    def load(
        cls, name: str, arguments: type[A], result: Any, *, uses: tuple[str, ...] = ()
    ) -> Script[A, R]:
        main = cls._source(f"{name}.js")
        if uses:
            helpers = "\n".join(cls._source(f"lib/{helper}.js") for helper in uses)
            main = (
                f"function(args, ...nodes) {{\n{helpers}\n"
                f"return ({main}).call(this, args, ...nodes);\n}}"
            )
        adapter: TypeAdapter[R] = TypeAdapter(result)
        return cls(name, main, arguments, adapter.validate_python)

    @staticmethod
    @cache
    def _source(path: str) -> str:
        return files(__package__).joinpath(path).read_text(encoding="utf-8")


ELEMENT: Script[ElementArgs, Any] = Script.load(
    "element",
    ElementArgs,
    Any,
    uses=("geometry", "composed", "visibility", "hit", "elements"),
)
SCROLL: Script[ScrollArgs, ScrollPlan | None] = Script.load(
    "scroll",
    ScrollArgs,
    ScrollPlan | None,
    uses=("geometry", "composed", "elements", "scroll"),
)
SCROLL_OWNER: Script[OwnerScrollArgs, ScrollPlan | None] = Script.load(
    "owner_scroll",
    OwnerScrollArgs,
    ScrollPlan | None,
    uses=("geometry", "composed", "elements", "scroll"),
)
CONTENT: Script[ContentArgs, ContentExtraction] = Script.load(
    "content",
    ContentArgs,
    ContentExtraction,
    uses=("composed", "visibility", "markdown"),
)
FIND: Script[FindArgs, FindResult] = Script.load(
    "find", FindArgs, FindResult, uses=("composed",)
)
STABILITY: Script[ScriptArgs, DOMProbe] = Script.load("stability", ScriptArgs, DOMProbe)
SEED: Script[SeedArgs, None] = Script.load("seed", SeedArgs, type(None))
RESET: Script[ScriptArgs, None] = Script.load("reset", ScriptArgs, type(None))
FOCUSED: Script[ScriptArgs, Any] = Script.load("focused", ScriptArgs, Any)
CURSOR: Script[CursorArgs, str] = Script.load("cursor", CursorArgs, str)
TAB_STRIP: Script[ScriptArgs, TabStrip] = Script.load("tab_strip", ScriptArgs, TabStrip)
PAGE_FACTS: Script[ScriptArgs, PageFacts] = Script.load(
    "page_facts", ScriptArgs, PageFacts
)
VIEWPORT: Script[ScriptArgs, tuple[float, float]] = Script.load(
    "viewport", ScriptArgs, tuple[float, float]
)
OWNER_SIZE: Script[ScriptArgs, tuple[float, float] | None] = Script.load(
    "owner_size",
    ScriptArgs,
    tuple[float, float] | None,
    uses=("composed", "visibility"),
)
OWNER_HITS: Script[OwnerHitsArgs, tuple[bool, ...]] = Script.load(
    "owner_hits",
    OwnerHitsArgs,
    tuple[bool, ...],
    uses=("geometry", "composed", "visibility", "hit"),
)

SECRET_FIELD: Script[SecretFieldArgs, SecretField] = Script.load(
    "secret_field", SecretFieldArgs, SecretField, uses=("secret",)
)
SECRET_FOCUS: Script[SecretFocusArgs, SecretFocus] = Script.load(
    "secret_focus", SecretFocusArgs, SecretFocus, uses=("secret",)
)


def failure(script: Script, details: Any) -> str:
    detail = details.exception
    message = detail.description if detail is not None else details.text
    # Only exact first-line error codes are trusted; page exception text stays private.
    match = re.match(r"^(?:Error: )?([A-Z_]+)(?:\n|$)", message or "")
    if match and match[1] in ScriptError:
        return match[1]
    return f"{script.name} failed in the page"
