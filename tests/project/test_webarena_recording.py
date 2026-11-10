"""Free local integration check: Browserrig actions must reach the official HAR."""

import asyncio
import json

import pytest

from browserrig.browser import ChromeBrowser, Connect
from evals.environments import Environments
from evals.recording import recording_browser
from evals.task import load_tasks


@pytest.mark.integration
async def test_browserrig_records_navigation_in_the_recording_context(site, tmp_path):
    pytest.importorskip("playwright.async_api")
    _, tasks = load_tasks()
    task = tasks[0].model_copy(
        update={
            "start_urls": ("__REDDIT__/", "__REDDIT__/other"),
            "sites": ("reddit",),
        }
    )
    environments = Environments()
    environments.sites["reddit"] = environments.sites["reddit"].model_copy(
        update={"url": site, "username": ""}
    )
    async with (
        recording_browser(task, environments, tmp_path, headless=True) as (
            endpoint,
            target,
        ),
        ChromeBrowser(Connect(endpoint=endpoint, target_id=target)) as browser,
    ):
        assert browser.active_tab.url.rstrip("/") == site
        await browser.active_tab.navigate(site + "/links")
        await browser.tabs.open(site + "/other")
    har = json.loads((tmp_path / "network.har").read_bytes())
    entries = har["log"]["entries"]
    urls = {entry["request"]["url"] for entry in entries}
    assert {site + "/", site + "/links", site + "/other"} <= urls
    body = next(
        entry["response"]["content"]["text"]
        for entry in entries
        if entry["request"]["url"] == site + "/links"
    )
    assert "Plain link" in body


@pytest.mark.integration
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_recording_flushes_evidence_when_an_attempt_is_interrupted(
    site, tmp_path, error
):
    _, tasks = load_tasks()
    task = tasks[0].model_copy(
        update={"start_urls": ("__REDDIT__/",), "sites": ("reddit",)}
    )
    environments = Environments()
    environments.sites["reddit"] = environments.sites["reddit"].model_copy(
        update={"url": site, "username": ""}
    )
    with pytest.raises(error):
        async with recording_browser(task, environments, tmp_path, headless=True):
            raise error("interrupted attempt")
    entries = json.loads((tmp_path / "network.har").read_bytes())["log"]["entries"]
    assert any(entry["request"]["url"] == site + "/" for entry in entries)


@pytest.fixture
async def login_site():
    async def handle(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            path = headers.split(b" ")[1]
            length = next(
                (
                    int(line.split(b":", 1)[1])
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                ),
                0,
            )
            if length:
                await reader.readexactly(length)
            extra = ""
            if path == b"/users/sign_in":
                body = b"""<form method=post action=/session>
                    <label>Username or email<input name=username></label>
                    <label>Password<input type=password name=password></label>
                    <button>Sign in</button></form>"""
            else:
                if path == b"/session":
                    extra = "Set-Cookie: session=authenticated; Path=/\r\n"
                signed_in = path == b"/session" or b"session=authenticated" in headers
                body = b"Signed in" if signed_in else b"Signed out"
            writer.write(
                (
                    f"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n{extra}"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + body
            )
            await writer.drain()
        except asyncio.IncompleteReadError:
            pass  # Chrome may close a speculative connection before sending a request.
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    async with server:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"


@pytest.mark.integration
async def test_authenticated_state_is_transferred_without_recording_login(
    login_site, tmp_path
):
    from pydantic import SecretStr  # pylint: disable=import-outside-toplevel

    _, tasks = load_tasks()
    task = tasks[0].model_copy(
        update={"start_urls": ("__GITLAB__/",), "sites": ("gitlab",)}
    )
    environments = Environments()
    environments.sites["gitlab"] = environments.sites["gitlab"].model_copy(
        update={
            "url": login_site,
            "username": "smoke-user",
            "password": SecretStr("smoke-password"),
        }
    )
    async with (
        recording_browser(task, environments, tmp_path, headless=True) as (
            endpoint,
            target,
        ),
        ChromeBrowser(Connect(endpoint=endpoint, target_id=target)) as browser,
    ):
        assert (
            json.loads(await browser.active_tab.evaluate("document.body.textContent"))
            == "Signed in"
        )
        assert (
            json.loads(await browser.active_tab.evaluate("navigator.language"))
            == "en-US"
        )
        assert (
            json.loads(
                await browser.active_tab.evaluate(
                    "Intl.DateTimeFormat().resolvedOptions().timeZone"
                )
            )
            == "UTC"
        )
    raw = (tmp_path / "network.har").read_text(encoding="utf-8")
    entries = json.loads(raw)["log"]["entries"]
    assert any(entry["request"]["url"] == login_site + "/" for entry in entries)
    assert not any(
        entry["request"]["url"].endswith(("/users/sign_in", "/session"))
        for entry in entries
    )
    assert "smoke-password" not in raw
