"""Cancellation during teardown must not interrupt the evaluator's HAR flush."""

import asyncio
from types import SimpleNamespace

import pytest

from evals.plugins import NetworkRecording


async def test_har_close_finishes_before_cancellation_propagates(tmp_path):
    closing, release = asyncio.Event(), asyncio.Event()
    flushed = []

    async def close():
        closing.set()
        await release.wait()
        flushed.append(True)

    async def new_context(**_options):
        return SimpleNamespace(close=close)

    async def attempt():
        async with NetworkRecording(tmp_path / "network.har").context(
            SimpleNamespace(new_context=new_context), {}
        ):
            pass

    task = asyncio.create_task(attempt())
    try:
        await asyncio.wait_for(closing.wait(), 2)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert flushed == [True]
