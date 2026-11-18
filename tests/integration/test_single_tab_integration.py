import asyncio
from functools import partial

import pytest
from cdpify.domains.target import TargetDestroyedEvent
from harnessed.testing import ScriptedModel

from browserrig import (
    Agent,
    Browser,
    BrowserPerception,
    Choreography,
    ChoreographyOverlay,
    Chrome,
    ChromeBrowser,
    InputPacing,
    SingleTab,
    TabPolicy,
    TabStrip,
    wait_for_page,
)
from browserrig.browser import Connect, Launch
from browserrig.core import BrowserError

pytestmark = pytest.mark.integration

_PAGES = {
    "/link": '<a id=go href="/destination" target=_blank>Go</a>',
    "/named": '<a id=go href="/destination" target=results>Go</a>',
    "/base": '<base target=_blank><a id=go href="/destination">Go</a>',
    "/window": "<button id=go onclick=\"window.open('/destination')\">Go</button>",
    "/post": '<form action="/destination" method=post target=_blank>'
    "<input name=token value=kept><button id=go>Go</button></form>",
    "/submitter": '<form action="/destination" method=post>'
    "<input name=token value=kept><button id=go formtarget=_blank>Go</button></form>",
    "/programmatic": '<form action="/destination" method=post target=_blank>'
    "<input name=token value=kept></form>"
    "<button id=go onclick=\"document.querySelector('form').submit()\">Go</button>",
    "/early": '<script>window.open("/destination")</script>',
    "/frame": '<iframe src="/link"></iframe>',
}


async def test_single_tab_policy_is_installed_before_the_agents_first_page(
    routing_site,
):
    site, requests = routing_site
    model = ScriptedModel(["Done"])
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=site + "/early"),
        plugins=[SingleTab()],
        without=(InputPacing, Choreography, ChoreographyOverlay, TabStrip),
    )
    async with agent.session() as session:
        result = await session.run("Observe the initial page", max_steps=1)
        assert result.text == "Done"
        browser = session.scope[Browser]
        snapshot = session.scope[BrowserPerception].snapshot
        assert snapshot is not None and snapshot.tabs == ()
        assert snapshot.url == browser.active_tab.url == site + "/destination"
        assert len(await browser.tabs.list()) == 1
        assert not {"open_tab", "list_tabs", "switch_tab", "close_tab"} & set(
            session.tools
        )
        prompt = await session.prompt.render()
        assert "Multiple browser tabs" not in prompt and "new_tab" not in prompt
    assert sum(path == "/early" for _, path, _ in requests) == 1
    assert all(
        "tabs (* = this tab)" not in message.text
        for message in model.requests[0].messages
    )


@pytest.mark.parametrize("path", list(_PAGES))
async def test_single_tab_routes_links_forms_and_scripts_with_history(
    routing_site, path
):
    site, requests = routing_site
    async with ChromeBrowser(
        Launch(url=site + path), tab_policy=TabPolicy(multiple=False)
    ) as browser:
        tab = browser.active_tab
        original = tab.id
        await wait_for_page(tab)
        if path != "/early":
            expression = "document.getElementById('go').click()"
            if path == "/frame":
                expression = (
                    "document.querySelector('iframe').contentDocument"
                    ".getElementById('go').click()"
                )
            await wait_for_page(
                tab,
                dispatch=partial(tab.evaluate, expression),
            )
        assert tab.url == site + "/destination"
        assert browser.active_tab.id == original
        assert [entry.id for entry in await browser.tabs.list()] == [original]
        destinations = [request for request in requests if request[1] == "/destination"]
        assert len(destinations) == 1
        if path in {"/post", "/submitter", "/programmatic"}:
            assert destinations == [("POST", "/destination", b"token=kept")]
        if path != "/early":
            await wait_for_page(tab, dispatch=tab.go_back)
            assert tab.url == site + path


async def test_single_tab_open_reuses_current_tab_for_urls_and_host_files(
    site, tmp_path
):
    path = tmp_path / "preview.html"
    path.write_text(
        "<title>Local preview</title><p>Preview content</p>", encoding="utf-8"
    )
    async with ChromeBrowser(tab_policy=TabPolicy(multiple=False)) as browser:
        original = browser.active_tab.id
        navigated = await browser.tabs.open(site + "/other")
        await wait_for_page(navigated)
        assert navigated.id == original and navigated.url == site + "/other"
        preview = await browser.tabs.open(path)
        await wait_for_page(preview)
        assert preview.id == original and preview.url.startswith("file:")
        assert "Preview content" in await preview.evaluate("document.body.textContent")
        assert len(await browser.tabs.list()) == 1


async def test_single_tab_disconnect_restores_page_and_preserves_other_tabs(site):
    async with ChromeBrowser(Launch(url=site + "/links")) as owner:
        first = owner.active_tab
        await wait_for_page(first)
        sibling = await owner.tabs.open()
        native_open = await first.evaluate("String(window.open)")
        options = Connect(endpoint=owner.client.transport.url, target_id=first.id)
        async with ChromeBrowser(
            options, tab_policy=TabPolicy(multiple=False)
        ) as connected:
            controlled = connected.active_tab
            assert "native code" not in await controlled.evaluate("String(window.open)")
            assert [entry.id for entry in await connected.tabs.list()] == [first.id]
            assert await controlled.evaluate("window.open()") == "null"
            with pytest.raises(BrowserError, match="popup.*single-tab mode"):
                controlled.check_navigation()
        assert await first.evaluate("String(window.open)") == native_open
        assert sibling.id in {entry.id for entry in await owner.tabs.list()}


async def test_single_tab_closes_a_popup_from_a_cached_native_function(site):
    async with ChromeBrowser(Launch(url=site + "/links")) as owner:
        original = owner.active_tab
        await wait_for_page(original)
        await original.evaluate("window.savedOpen = window.open; void 0")
        options = Connect(endpoint=owner.client.transport.url, target_id=original.id)
        async with ChromeBrowser(
            options, tab_policy=TabPolicy(multiple=False)
        ) as connected:
            async with connected.client.listen(TargetDestroyedEvent) as destroyed:
                await connected.active_tab.evaluate("void window.savedOpen('/other')")
                async with asyncio.timeout(10):
                    closed = await anext(destroyed)
            assert closed.target_id != original.id
            with pytest.raises(BrowserError, match="separate tab.*single-tab mode"):
                await connected.tabs.list()
            assert [entry.id for entry in await connected.tabs.list()] == [original.id]
            assert original.url == site + "/links"


@pytest.fixture(name="routing_site")
async def _routing_site():
    requests = []

    async def handle(reader, writer):
        try:
            async with asyncio.timeout(10):
                head = await reader.readuntil(b"\r\n\r\n")
                method, path, _ = head.split(b"\r\n", 1)[0].decode().split(" ")
                length = next(
                    (
                        int(line.split(b":", 1)[1])
                        for line in head.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    ),
                    0,
                )
                payload = await reader.readexactly(length)
                requests.append((method, path, payload))
                page = _PAGES.get(path, "<title>Destination</title><p>Arrived</p>")
                body = ("<!doctype html>" + page).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield f"http://127.0.0.1:{port}", requests
