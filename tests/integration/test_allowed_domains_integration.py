import asyncio
from contextlib import asynccontextmanager

import pytest
from harnessed import PolicyDecision
from harnessed.models import ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call

from browserrig import (
    Agent,
    AllowedDomains,
    Chrome,
    ChromeBrowser,
    DomainNotAllowed,
    InputPacing,
    InputVisualization,
    TabStrip,
    wait_for_page,
)
from browserrig.browser import Connect, Launch
from browserrig.events import NavigationBlockedEvent
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


@pytest.fixture(name="guarded_site")
async def _guarded_site():
    requests = []
    blocked = asyncio.Event()
    receipts = []

    async def emit(event):
        if isinstance(event, NavigationBlockedEvent):
            receipts.append(event)
            blocked.set()

    async def handle(reader, writer):
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            requests.append(raw.decode())
            path = raw.split(b" ")[1].decode()
            if path == "/redirect":
                response = (
                    f"HTTP/1.1 302 Found\r\nLocation: {denied}/destination\r\n"
                    "Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            else:
                body = (
                    f'<title>Allowed</title><a id=link href="{denied}/destination">Go</a>'
                    f"<button onclick=\"window.open('{denied}/destination')\">Popup</button>"
                )
                response = (
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                    f"Content-Length: {len(body.encode())}\r\nConnection: close\r\n\r\n{body}"
                )
            writer.write(response.encode())
            await writer.drain()
        except asyncio.IncompleteReadError:
            # Chrome may close speculative preconnects without sending a request.
            return
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    allowed, denied = f"http://127.0.0.1:{port}", f"http://localhost:{port}"
    try:
        yield allowed, denied, requests, blocked, receipts, emit
    finally:
        server.close()
        await server.wait_closed()


@asynccontextmanager
async def _browser(guarded_site):
    allowed, _, _, _, _, emit = guarded_site
    async with ChromeBrowser(
        Launch(url=allowed), navigation_policy=AllowedDomains("127.0.0.1"), emit=emit
    ) as browser:
        yield browser


async def test_explicit_navigation_and_open_are_rejected_before_requests(guarded_site):
    _, denied, requests, _, receipts, _ = guarded_site
    async with _browser(guarded_site) as browser:
        for operation in (browser.active_tab.navigate, browser.tabs.open):
            with pytest.raises(DomainNotAllowed):
                await operation(denied)
        assert len(receipts) == 2
        assert all("Host: localhost:" not in request for request in requests)


@pytest.mark.parametrize(
    "cause", ["redirect", "link", "popup", "iframe", "location", "form"]
)
async def test_browser_navigation_is_intercepted_before_destination_request(
    guarded_site, cause
):
    allowed, denied, requests, blocked, receipts, _ = guarded_site
    async with _browser(guarded_site) as browser:
        tab = browser.active_tab
        if cause == "redirect":
            with pytest.raises(DomainNotAllowed):
                await tab.navigate(allowed + "/redirect")
        elif cause == "link":
            await tab.evaluate("document.querySelector('#link').click()")
        elif cause == "popup":
            await tab.evaluate("document.querySelector('button').click()")
        elif cause == "iframe":
            await tab.evaluate(
                f"document.body.appendChild(document.createElement('iframe')).src = '{denied}'"
            )
        elif cause == "location":
            await tab.evaluate(f"location.href = '{denied}'")
        else:
            await tab.evaluate(
                "const form = document.body.appendChild(document.createElement('form'));"
                f"form.action = '{denied}'; form.method = 'POST'; form.submit()"
            )
        await asyncio.wait_for(blocked.wait(), timeout=5)
        assert receipts[-1].url.startswith(denied)
        assert all("Host: localhost:" not in request for request in requests)


async def test_plugin_is_active_before_chrome_opens_initial_url(guarded_site):
    _, denied, requests, _, _, _ = guarded_site
    agent = Agent(
        model=ScriptedModel([]),
        browser=Chrome.launch(url=denied),
        plugins=[
            AllowedDomains("127.0.0.1"),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    with pytest.RaisesGroup(DomainNotAllowed):
        async with agent.session():
            pytest.fail("A denied initial URL must not open a session")
    assert requests == []


async def test_model_receives_blocked_navigation_error_and_can_continue(guarded_site):
    allowed, denied, requests, _, _, _ = guarded_site
    model = ScriptedModel([call("navigate", url=denied), "Finished"])
    agent = Agent(
        model=model,
        browser=Chrome.launch(url=allowed),
        plugins=[
            AllowedDomains("127.0.0.1"),
            Approvals(default=PolicyDecision.ALLOW),
        ],
        without=(InputPacing, InputVisualization, TabStrip),
    )
    async with agent.session() as session:
        await session.run("Navigate", max_steps=3)
    replies = [m for m in model.requests[-1].messages if isinstance(m, ToolMessage)]
    assert replies[0].is_error
    assert f"Navigation blocked: domain is not allowed for {denied}" in replies[0].text
    assert all("Host: localhost:" not in request for request in requests)


async def test_without_policy_browsing_is_unrestricted(guarded_site):
    _, denied, requests, _, _, _ = guarded_site
    async with ChromeBrowser(Launch(url=denied)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        assert await tab.evaluate("location.hostname") == '"localhost"'
    assert any("Host: localhost:" in request for request in requests)


async def test_cross_process_frame_cannot_navigate_to_a_denied_domain(guarded_site):
    allowed, child, requests, blocked, receipts, emit = guarded_site
    denied = allowed.replace("127.0.0.1", "127.0.0.2")
    async with ChromeBrowser(
        Launch(url=allowed, arguments=("--site-per-process",)),
        navigation_policy=AllowedDomains(("127.0.0.1", "localhost")),
        emit=emit,
    ) as browser:
        tab = browser.active_tab
        await tab.evaluate(
            "new Promise(resolve => { const f = document.createElement('iframe');"
            f"f.src = '{child}'; f.onload = () => resolve(true);"
            "document.body.appendChild(f); })"
        )
        await wait_for_page(tab)
        frames = await tab.frames()
        assert len(frames) == 2
        assert frames[0].cdp.session_id != frames[1].cdp.session_id
        await evaluate(frames[1], f"location.href = '{denied}'")
        await asyncio.wait_for(blocked.wait(), timeout=5)
        assert receipts[-1].url.startswith(denied)
        assert all("Host: 127.0.0.2:" not in request for request in requests)


@pytest.mark.parametrize("attach", [False, True])
async def test_connected_browser_cleans_up_guard_without_restricting_other_tabs(
    guarded_site, attach
):
    allowed, denied, _, _, _, _ = guarded_site
    async with ChromeBrowser(Launch(url=allowed)) as host:
        existing = host.active_tab
        await wait_for_page(existing)
        options = Connect(
            endpoint=host.client.transport.url,
            target_id=existing.id if attach else None,
        )
        async with ChromeBrowser(
            options, navigation_policy=AllowedDomains("127.0.0.1")
        ) as guarded:
            with pytest.raises(DomainNotAllowed):
                await guarded.active_tab.navigate(denied)
            if not attach:
                await existing.navigate(denied)
        # An attached tab is still usable after the guard disconnects.
        await existing.navigate(denied)
        assert await existing.evaluate("location.hostname") == '"localhost"'
