from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from harnessed.kernel import PluginScope
from harnessed.tracing import Span, span

from browserrig.core import ActionKind, Point

from .policy import COORDINATE_KINDS

type Attribute = str | bool | int | float


@dataclass
class _Operation:
    span: Span
    active: bool = True


_current: ContextVar[_Operation | None] = ContextVar(
    "browserrig.operation", default=None
)


@contextmanager
def operation_span(scope: PluginScope, **attributes: Attribute) -> Generator[None]:
    with span("browserrig.operation", scope=scope, **attributes) as current:
        operation = _Operation(current)
        token = _current.set(operation)
        try:
            yield
        finally:
            operation.active = False
            _current.reset(token)


def record_target(kind: ActionKind, arguments: Mapping[str, object]) -> None:
    for key in ("ref", "source_ref", "target_ref", "target_id"):
        if isinstance(value := arguments.get(key), str):
            record_operation(**{f"target.{key}": value})
    if kind not in COORDINATE_KINDS:
        return
    for endpoint in ("start", "end"):
        if isinstance(point := arguments.get(endpoint), Point):
            record_point("input", point, endpoint=endpoint)
    x, y = arguments.get("x"), arguments.get("y")
    if isinstance(x, int | float) and isinstance(y, int | float):
        record_operation(**{"input.x": x, "input.y": y})


def record_point(space: str, point: Point, *, endpoint: str = "") -> None:
    prefix = f"{space}.{endpoint}" if endpoint else space
    record_operation(**{f"{prefix}.x": point.x, f"{prefix}.y": point.y})


def record_operation(**attributes: Attribute) -> None:
    operation = _current.get()
    if operation is not None and operation.active:
        for key, value in attributes.items():
            operation.span.set_attribute(f"browserrig.{key}", value)
