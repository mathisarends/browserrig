"""Milestones a task run must reach. Each check is scored on its own, so a long mission
shows how far the agent got instead of only pass or fail."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class Evidence:
    """Everything a check may look at once the run has finished."""

    answer: str
    completed: bool
    workspace: Path
    # name, args and error flag of every tool call, in order.
    tools: list[dict[str, Any]]
    # Model-visible history plus tool arguments, for leak checks.
    transcript: str
    # JavaScript probe results from the active tab, read before the browser closed.
    probes: dict[str, Any] = field(default_factory=dict)


class Check(Protocol):
    label: str

    def evaluate(self, evidence: Evidence) -> str | None:
        """None when the milestone is reached, else why not."""
        ...


type Expected = str | Callable[[], str]


def _resolve(value: Expected) -> str:
    return value() if callable(value) else value


@dataclass(frozen=True)
class Answer:
    """Every pattern matches the final answer (case-insensitive regex)."""

    label: str
    patterns: tuple[Expected, ...]

    def evaluate(self, evidence: Evidence) -> str | None:
        missing = [
            pattern
            for pattern in map(_resolve, self.patterns)
            if not re.search(pattern, evidence.answer, re.I | re.S)
        ]
        return f"answer lacks {missing}" if missing else None


@dataclass(frozen=True)
class Workspace:
    """At least `count` files match `pattern` in the workspace, optionally containing text."""

    label: str
    pattern: str
    count: int = 1
    contains: tuple[str, ...] = ()

    def evaluate(self, evidence: Evidence) -> str | None:
        found = [p for p in evidence.workspace.glob(self.pattern) if p.is_file()]
        if len(found) < self.count:
            names = sorted(
                str(p.relative_to(evidence.workspace))
                for p in evidence.workspace.rglob("*")
                if p.is_file()
            )
            return f"{len(found)}/{self.count} files match {self.pattern}; workspace: {names}"
        for pattern in self.contains:
            if not any(
                re.search(pattern, p.read_text("utf-8", "replace"), re.I | re.S)
                for p in found
            ):
                return f"no {self.pattern} contains {pattern!r}"
        return None


@dataclass(frozen=True)
class ToolUsed:
    """The agent called this tool at least `count` times without an error."""

    label: str
    name: str
    count: int = 1

    def evaluate(self, evidence: Evidence) -> str | None:
        calls = sum(t["name"] == self.name and not t["error"] for t in evidence.tools)
        return (
            None
            if calls >= self.count
            else f"{self.name} succeeded {calls}/{self.count} times"
        )


@dataclass(frozen=True)
class Probe:
    """A JavaScript expression on the active tab, evaluated before the browser closes.

    `expect` receives the parsed JSON value and returns True when the milestone holds.
    """

    label: str
    expression: str
    expect: Callable[[Any], bool]

    def evaluate(self, evidence: Evidence) -> str | None:
        if self.expression not in evidence.probes:
            return "probe did not run"
        value = evidence.probes[self.expression]
        if isinstance(value, dict) and "probe_error" in value:
            return f"probe failed: {value['probe_error']}"
        try:
            held = self.expect(value)
        except Exception as error:  # noqa: BLE001 - a malformed page value is a miss
            held = False
            value = f"{value!r} ({type(error).__name__})"
        return (
            None if held else f"probe returned {json.dumps(value, default=str)[:300]}"
        )


@dataclass(frozen=True)
class NoLeak:
    """The secret value never reaches the answer, tool arguments or model history."""

    label: str
    value: str

    def evaluate(self, evidence: Evidence) -> str | None:
        places = [
            name
            for name, text in (
                ("answer", evidence.answer),
                ("transcript", evidence.transcript),
            )
            if self.value in text
        ]
        return f"secret visible in {places}" if places else None


@dataclass(frozen=True)
class Custom:
    """Any other condition on the evidence; `test` returns None or a reason."""

    label: str
    test: Callable[[Evidence], str | None]

    def evaluate(self, evidence: Evidence) -> str | None:
        return self.test(evidence)
