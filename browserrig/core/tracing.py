"""Method spans under the session's Harnessed tracer, so traces show where browser time goes.

The Chrome plugin binds the session's tracer around each tool call and model step.
Inside, `traced` methods open a span named after the method, with its source file and
line, and nest below the Harnessed step or tool span. Without a configured tracer
nothing is recorded and a traced call costs one context lookup.
"""

import functools
import inspect
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

from harnessed.core.tracing import Span, Tracer

_ROOT = Path(__file__).resolve().parents[2]
_tracer: ContextVar[Tracer | None] = ContextVar("browserrig_tracer", default=None)
_span: ContextVar[Span | None] = ContextVar("browserrig_span", default=None)


@contextmanager
def use_tracer(tracer: Tracer | None) -> Generator[None]:
    """Record traced methods called in this context, including tasks it starts."""
    token = _tracer.set(tracer)
    try:
        yield
    finally:
        _tracer.reset(token)


def traced[F: Callable[..., Any]](fn: F) -> F:
    """Open a span named after `fn` for each call, with its source location."""
    location = _location(fn)
    name = location["code.function"]
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            tracer = _tracer.get()
            if tracer is None:
                return await fn(*args, **kwargs)
            with _open(tracer, name, location):
                return await fn(*args, **kwargs)

        return cast(F, run_async)

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        tracer = _tracer.get()
        if tracer is None:
            return fn(*args, **kwargs)
        with _open(tracer, name, location):
            return fn(*args, **kwargs)

    return cast(F, run)


@contextmanager
def span(name: str) -> Generator[None]:
    """Trace a block inside a method, located at the line that opens it."""
    tracer = _tracer.get()
    if tracer is None:
        yield
        return
    caller = inspect.currentframe()
    caller = caller.f_back.f_back if caller and caller.f_back else None
    location = (
        {
            "code.filepath": _path(caller.f_code.co_filename),
            "code.lineno": caller.f_lineno,
        }
        if caller is not None
        else {}
    )
    with _open(tracer, name, location):
        yield


def record(**attributes: str | bool | int | float) -> None:
    """Add results, such as a readiness status, to the innermost browserrig span."""
    current = _span.get()
    if current is None:
        return
    for key, value in attributes.items():
        current.set_attribute(key, value)


@contextmanager
def _open(tracer: Tracer, name: str, location: dict[str, Any]) -> Generator[None]:
    with tracer.span(name, **location) as current:
        token = _span.set(current)
        try:
            yield
        finally:
            _span.reset(token)


def _location(fn: Callable[..., Any]) -> dict[str, Any]:
    name = getattr(fn, "__qualname__", repr(fn))
    code = getattr(inspect.unwrap(fn), "__code__", None)
    if code is None:
        return {"code.function": name}
    return {
        "code.function": name,
        "code.namespace": fn.__module__,
        "code.filepath": _path(code.co_filename),
        "code.lineno": code.co_firstlineno,
    }


def _path(filename: str) -> str:
    path = Path(filename).resolve()
    return (
        path.relative_to(_ROOT).as_posix() if path.is_relative_to(_ROOT) else filename
    )
