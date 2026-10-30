from __future__ import annotations

import html
import json
import re
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from typing import Any, cast
from urllib.parse import quote, quote_plus

from pydantic import BaseModel

from .models import placeholder

# Identifiers, digests and binary payloads are never text a secret can appear in.
_OPAQUE_FIELDS = frozenset({"id", "ref", "type", "fingerprint", "image"})


class Redactor:
    """Replace known secret values, including common encodings, with their placeholders.

    Matching ignores case so transformed page text such as upper-cased echoes stays hidden.
    """

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None

    def __bool__(self) -> bool:
        return self._pattern is not None

    def add(self, name: str, value: str) -> None:
        variants = {
            value,
            quote(value, safe=""),
            quote(value),
            quote_plus(value),
            html.escape(value),
            html.escape(value, quote=False),
            json.dumps(value)[1:-1],
            json.dumps(value, ensure_ascii=False)[1:-1],
        }
        added = False
        for variant in variants:
            key = variant.casefold()
            if key not in self._names:
                self._names[key] = name
                added = True
        if added:
            # Longest first, so a value never leaves the tail of a longer one visible.
            ordered = sorted(self._names, key=len, reverse=True)
            self._pattern = re.compile(
                "|".join(re.escape(variant) for variant in ordered), re.IGNORECASE
            )

    def contains(self, text: str) -> bool:
        return self._pattern is not None and self._pattern.search(text) is not None

    def text(self, text: str) -> str:
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(self._replace, text)

    def scrub[T](self, value: T) -> T:
        """Redact all text in nested models, dataclasses and containers; others pass through."""
        if self._pattern is None:
            return value
        return cast(T, self._scrub(value))

    def _replace(self, match: re.Match[str]) -> str:
        name = self._names.get(match.group(0).casefold())
        return placeholder(name) if name is not None else "{{secret}}"

    def _scrub(self, value: Any) -> Any:  # pylint: disable=too-many-return-statements
        if value is None or isinstance(value, (Enum, bool, int, float)):
            return value
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, tuple):
            items = tuple(self._scrub(item) for item in value)
            if items == value:
                return value
            # Named tuples need their concrete constructor; plain tuples do not.
            return items if type(value) is tuple else type(value)(*items)  # pylint: disable=unidiomatic-typecheck
        if isinstance(value, list):
            return [self._scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: self._scrub(item) for key, item in value.items()}
        if isinstance(value, BaseModel):
            update = self._changed(value, type(value).model_fields)
            return value.model_copy(update=update) if update else value
        if is_dataclass(value) and not isinstance(value, type):
            names = [item.name for item in fields(value) if item.init]
            update = self._changed(value, names)
            return replace(value, **update) if update else value
        return value

    def _changed(self, value: object, names: Any) -> dict[str, Any]:
        update = {}
        for name in names:
            if name in _OPAQUE_FIELDS or name.endswith("_id") or name.endswith("_ids"):
                continue
            current = getattr(value, name)
            scrubbed = self._scrub(current)
            if scrubbed is not current and scrubbed != current:
                update[name] = scrubbed
        return update
