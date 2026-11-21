import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify import CDPCommandError
from harnessed import Agent, Plugin
from harnessed.kernel import PluginScope
from harnessed.testing import ScriptedModel

from browserrig import Browser, Screencast
from browserrig.core import BrowserError


async def test_live_stream_acks_every_frame_and_keeps_latest_for_viewer():
    source = _Source()
    await source.frames.put(_frame(1))
    await source.frames.put(_frame(2))
    agent = Agent(
        model=ScriptedModel([]), plugins=[_BrowserService(source), Screencast()]
    )

    async with asyncio.timeout(5), AsyncExitStack() as viewer:
        async with agent.session() as session:
            screencast = session.scope[Screencast]
            frames = await viewer.enter_async_context(screencast.open())
            await source.acked.wait()
            latest = await anext(frames)
            assert (latest.target_id, latest.data, latest.mime_type) == (
                "tab",
                "frame 2",
                "image/jpeg",
            )
            assert latest.timestamp_seconds == 2
            assert source.acks == [1, 2]
            with pytest.raises(BrowserError, match="already open"):
                async with screencast.open():
                    pytest.fail("A second viewer opened")
            pending = asyncio.create_task(anext(frames, None))
        assert await pending is None
    source.page.stop_screencast.assert_awaited_once()
    assert not source.listening


async def test_failed_start_reaches_viewer_and_allows_retry():
    source = _Source()
    reason = CDPCommandError("Page.startScreencast", -32000, "could not start")
    source.page.start_screencast.side_effect = reason
    agent = Agent(model=ScriptedModel([]), plugins=[_BrowserService(source)])

    async with (
        agent.session() as session,
        asyncio.timeout(5),
        session.mount(Screencast()),
    ):
        screencast = session.scope[Screencast]
        async with screencast.open() as frames:
            with pytest.raises(BrowserError, match="Live screencast failed") as error:
                await anext(frames)
            assert error.value.__cause__ is reason
        assert not source.listening
        source.page.start_screencast.side_effect = None
        await source.frames.put(_frame(1))
        async with screencast.open() as frames:
            assert (await anext(frames)).data == "frame 1"
    assert source.page.stop_screencast.await_count == 2


class _Source:
    def __init__(self):
        self.frames: asyncio.Queue[SimpleNamespace] = asyncio.Queue()
        self.acked = asyncio.Event()
        self.acks: list[int] = []
        self.listening = False
        self.page = SimpleNamespace(
            start_screencast=AsyncMock(),
            stop_screencast=AsyncMock(),
            screencast_frame_ack=self._ack,
        )

    @asynccontextmanager
    async def listen(self, _event_type, *, max_queue_size):
        assert max_queue_size > 0
        self.listening = True
        try:
            yield self._events()
        finally:
            self.listening = False

    async def _events(self):
        while True:
            yield await self.frames.get()

    async def _ack(self, *, session_id):
        self.acks.append(session_id)
        if session_id == 2:
            self.acked.set()


class _BrowserService(Plugin):
    def __init__(self, source):
        super().__init__()
        self.source = source

    async def setup(self, scope: PluginScope) -> None:
        tab = SimpleNamespace(id="tab", cdp=self.source, closed=False)
        tabs = SimpleNamespace(focused=lambda: tab)
        scope.provide(Browser, SimpleNamespace(tabs=tabs))


def _frame(index):
    return SimpleNamespace(
        data=f"frame {index}",
        session_id=index,
        metadata=SimpleNamespace(timestamp=float(index)),
    )
