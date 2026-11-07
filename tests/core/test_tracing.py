from contextlib import contextmanager

from browserrig.core import record, span, traced, use_tracer


class RecordingTracer:
    def __init__(self):
        self.spans = []

    @contextmanager
    def span(self, name, **attributes):
        current = {"name": name, **attributes}
        self.spans.append(current)
        yield _Attributes(current)


class _Attributes:
    def __init__(self, values):
        self._values = values

    def set_attribute(self, name, value):
        self._values[name] = value


@traced
async def fetch(value):
    record(size=len(value))
    return value.upper()


@traced
def assemble(value):
    with span("parse"):
        record(parsed=True)
    return value


async def test_traced_calls_are_named_after_their_source():
    tracer = RecordingTracer()
    with use_tracer(tracer):
        assert await fetch("abc") == "ABC"
        assert assemble("x") == "x"
    assert len(tracer.spans) == 3
    fetched, assembled, parsed = tracer.spans[0], tracer.spans[1], tracer.spans[2]
    assert fetched["name"] == "fetch"
    assert fetched["code.filepath"] == "tests/core/test_tracing.py"
    assert fetched["code.lineno"] == fetch.__wrapped__.__code__.co_firstlineno
    assert fetched["size"] == 3
    assert assembled["code.function"] == "assemble"
    # A block names the line that opens it and receives records made inside it.
    assert parsed["name"] == "parse"
    assert parsed["code.lineno"] == assemble.__wrapped__.__code__.co_firstlineno + 2
    assert parsed["parsed"] is True and "parsed" not in assembled


async def test_without_a_tracer_calls_run_untraced():
    assert await fetch("abc") == "ABC"
    with use_tracer(None):
        assert assemble("x") == "x"
    record(ignored=True)
