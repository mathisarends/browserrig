import asyncio

import pytest

from browserrig import BrowserCoordination


async def test_cancelling_a_waiter_preserves_ownership_and_cancelling_owner_releases_it():
    coordination = BrowserCoordination()
    entered, waiting, acquired = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def owner():
        async with coordination.exclusive():
            entered.set()
            await asyncio.Event().wait()

    async def waiter():
        waiting.set()
        async with coordination.exclusive():
            acquired.set()

    async with asyncio.timeout(5):
        first = asyncio.create_task(owner())
        await entered.wait()
        second = asyncio.create_task(waiter())
        await waiting.wait()
        assert coordination.busy and not acquired.is_set()
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert coordination.busy and not acquired.is_set()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not coordination.busy
        await waiter()
        assert acquired.is_set() and not coordination.busy


async def test_failed_operation_releases_control():
    coordination = BrowserCoordination()
    with pytest.raises(ValueError, match="failed"):
        async with coordination.exclusive():
            raise ValueError("failed")
    async with coordination.exclusive():
        assert coordination.busy
    assert not coordination.busy
