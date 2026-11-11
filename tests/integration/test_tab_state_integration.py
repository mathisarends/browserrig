import asyncio
import base64
from collections.abc import AsyncIterator

import pytest
from harnessed import Agent, PolicyDecision
from harnessed.models import ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import Chrome, InputRuntime, Runtime, browser_plugins
from browserrig.browser import Browser, Launch
from browserrig.choreography import TabStrip
from browserrig.events import NavigationStartedEvent, TabOpenedEvent, TabUpdatedEvent

pytestmark = pytest.mark.integration

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_INLINE = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'/>"
_RESOURCES = {
    "/": (
        b"text/html",
        b"<!doctype html><title>Icons</title><link rel=icon href=/icon.png>",
    ),
    "/inline": (
        b"text/html",
        f'<!doctype html><title>Inline</title><link rel=icon href="{_INLINE}">'.encode(),
    ),
    "/icon.png": (b"image/png", _PNG),
}


@pytest.fixture(name="icon_site")
async def icon_site_fixture() -> AsyncIterator[str]:
    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            path = (await reader.readline()).split()[1].decode()
            while (await reader.readline()).strip():
                pass
            found = _RESOURCES.get(path)
            status, (media_type, body) = (
                (b"200 OK", found)
                if found
                else (b"404 Not Found", (b"text/html", b"missing"))
            )
            writer.write(
                b"HTTP/1.1 "
                + status
                + b"\r\nContent-Type: "
                + media_type
                + f"\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def test_tab_updates_carry_loading_title_and_icons(icon_site):
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=[Runtime(), InputRuntime(), Chrome(Launch()), TabStrip()],
    )
    events: list[TabUpdatedEvent] = []
    async with agent.session() as session:

        async def collect() -> None:
            async for event in session.subscribe(transient=True):
                if isinstance(event, TabUpdatedEvent):
                    events.append(event)

        collector = asyncio.create_task(collect())
        await asyncio.sleep(0)
        tab = session.scope[Browser].active_tab
        try:
            for path, prefix in (
                ("/", "data:image/png;base64,"),
                ("/inline", "data:image/svg+xml"),
            ):
                await tab.navigate(icon_site + path)
                async with asyncio.timeout(10):
                    while not (
                        events
                        and events[-1].url == icon_site + path
                        and events[-1].favicon.startswith(prefix)
                    ):
                        await asyncio.sleep(0.05)
        finally:
            collector.cancel()
    assert any(event.loading for event in events)
    assert not events[-1].loading
    assert {event.title for event in events} >= {"Icons", "Inline"}


async def test_navigate_can_open_the_url_in_a_new_tab(icon_site):
    model = ScriptedModel(
        [call("navigate", url=icon_site + "/", new_tab=True), call("list_tabs"), "Done"]
    )
    agent = Agent(
        model=model,
        plugins=[
            *browser_plugins(browser=Chrome.launch(url=icon_site + "/inline")),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Open the page in a new tab", max_steps=3)
    assert result.text == "Done"
    opened = [event for event in result.events if isinstance(event, TabOpenedEvent)]
    started = [
        event for event in result.events if isinstance(event, NavigationStartedEvent)
    ]
    assert len(opened) == 1
    assert [(event.target_id, event.typed) for event in started] == [
        (opened[0].target_id, icon_site.removeprefix("http://"))
    ]
    replies = [
        msg for msg in model.requests[-1].messages if isinstance(msg, ToolMessage)
    ]
    assert not any(reply.is_error for reply in replies)
    assert f"{icon_site}/inline" in str(replies[-1].content)
    assert f"{icon_site}/" in str(replies[-1].content)
