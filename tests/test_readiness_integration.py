import asyncio
from contextlib import suppress

import pytest
from harnessed import Agent
from harnessed.testing import ScriptedModel

from browserrig import (
    Actions,
    Browser,
    ChromeBrowser,
    Launch,
    Observe,
    Point,
    ReadinessOptions,
    browser_plugins,
    wait_for_page,
)
from browserrig.core import ActionKind, ReadinessPhase
from browserrig.events import ReadinessDegradedEvent
from browserrig.tools.execution import Effect
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


@pytest.fixture(name="readiness_site")
async def readiness_server():
    async def handle(reader, writer):
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            path = raw.split(b" ")[1].decode()
            if path == "/slow":
                await asyncio.sleep(0.65)
                body = "<h1>Destination ready</h1>"
            elif path == "/very-slow":
                await asyncio.sleep(2.5)
                body = "<h1>Late destination</h1>"
            elif path in {"/frame", "/cross-frame"}:
                source = (
                    "/child"
                    if path == "/frame"
                    else base.replace("127.0.0.1", "localhost") + "/child"
                )
                body = f"<iframe src='{source}'></iframe>"
            elif path == "/child":
                body = """<h1>Initial child</h1><script>
                    addEventListener('message', () => {
                      setTimeout(()=>document.querySelector('h1').textContent='Pending child',80);
                      setTimeout(()=>document.querySelector('h1').textContent='Final child',200);
                    });</script>"""
            else:
                body = """<button
                    style='position:absolute;left:10px;top:10px;width:180px;height:40px'
                    onclick="setTimeout(()=>location.assign('/slow'),500)">
                    Delayed navigation</button>
                    <div id=box style='width:40px;height:40px;background:red;margin-top:70px'></div>
                    <div id=host></div><script>
                    window.shadow=host.attachShadow({mode:'open'});
                    shadow.innerHTML='<p>Initial shadow</p>';
                    </script>"""
            data = ("<!doctype html><title>Readiness</title>" + body).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                + f"Content-Length: {len(data)}\r\n\r\n".encode()
                + data
            )
            await writer.drain()
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    try:
        yield base
    finally:
        server.close()
        await server.wait_closed()


async def test_delayed_click_navigation_settles_the_destination(readiness_site):
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=browser_plugins(Launch(url=readiness_site), local_files=False),
    )
    async with agent.session() as session:
        browser, observe = session.ctx[Browser], session.ctx[Observe]
        await observe.capture()

        async def click(_tab):
            await browser.mouse.click(Point(x=60, y=30))
            return Effect("Clicked.")

        await session.ctx[Actions].run(kind=ActionKind.CLICK, operation=click)
        snapshot = await observe.capture()
        assert snapshot.url == readiness_site + "/slow"
        assert snapshot.text == "Destination ready"
        assert snapshot.readiness == "ready"


async def test_shadow_mutations_and_newly_attached_roots_are_observed(readiness_site):
    async with ChromeBrowser(Launch(url=readiness_site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab, options=_options())
        await tab.evaluate("""
            shadow.innerHTML='<p>Pending shadow</p>';
            const added=document.createElement('div'); document.body.append(added);
            window.extra=added.attachShadow({mode:'open'});
            extra.innerHTML='<p>Pending extra</p>';
            for (let delay=40;delay<=200;delay+=40) {
              setTimeout(()=>{
                shadow.firstChild.textContent=delay===200?'Final shadow':'Pending '+delay;
                extra.firstChild.textContent=delay===200?'Final extra':'Pending '+delay;
              },delay);
            }
        """)
        report = await wait_for_page(
            tab, options=_options(), phase=ReadinessPhase.OBSERVATION
        )
        assert report.status == "ready"
        assert (
            await tab.evaluate("shadow.textContent + ' / ' + extra.textContent")
            == '"Final shadow / Final extra"'
        )


async def test_navigation_command_itself_is_bounded_before_the_response_commits(
    readiness_site,
):
    agent = Agent(
        model=ScriptedModel(["Done"]),
        plugins=browser_plugins(
            Launch(url=readiness_site),
            readiness=_options(timeout=0.5, navigation_min_ms=0),
            local_files=False,
        ),
    )
    async with agent.session() as session:
        observe = session.ctx[Observe]
        await observe.capture()

        async def navigate(tab):
            await tab.navigate(readiness_site + "/very-slow")
            return Effect("Navigated.")

        async with asyncio.timeout(2):
            result = await session.ctx[Actions].run(
                kind=ActionKind.NAVIGATE, operation=navigate
            )
            snapshot = await observe.capture()
        assert result.break_chain and "not confirmed" in result.text
        assert (
            snapshot.readiness == "degraded"
            and "budget exhausted" in snapshot.readiness_reason
        )


@pytest.mark.parametrize("path", ["/frame", "/cross-frame"])
async def test_frame_content_settles_including_cross_origin_frames(
    readiness_site, path
):
    async with ChromeBrowser(Launch(url=readiness_site + path)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab, options=_options())
        await tab.evaluate(
            "document.querySelector('iframe').contentWindow.postMessage('start','*')"
        )
        # The first child update is deliberately later than the old document's quiet time.
        report = await wait_for_page(
            tab, options=_options(), phase=ReadinessPhase.AFTER_ACTION
        )
        assert report.status == "ready"
        frames = await tab.frames()
        child = next(frame for frame in frames if frame.parent is not None)
        assert "Final child" in await evaluate(child, "document.body.textContent")


async def test_visible_finite_animations_settle_but_infinite_spinners_do_not_block(
    readiness_site,
):
    async with ChromeBrowser(Launch(url=readiness_site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab, options=_options())
        await tab.evaluate("""
            window.finite=box.animate([{transform:'translateX(0)'},{transform:'translateX(100px)'}],250);
            window.spinner=host.animate([{opacity:1},{opacity:0.5}],{duration:50,iterations:Infinity});
        """)
        report = await wait_for_page(
            tab, options=_options(), phase=ReadinessPhase.OBSERVATION
        )
        assert report.status == "ready"
        assert await tab.evaluate("finite.playState") == '"finished"'
        assert await tab.evaluate("spinner.playState") == '"running"'


async def test_an_observed_frame_can_navigate_from_same_origin_to_cross_origin(
    readiness_site,
):
    async with ChromeBrowser(Launch(url=readiness_site + "/frame")) as browser:
        tab = browser.active_tab
        await wait_for_page(tab, options=_options())
        destination = readiness_site.replace("127.0.0.1", "localhost") + "/child"
        await tab.evaluate(f"document.querySelector('iframe').src={destination!r}")
        report = await wait_for_page(
            tab, options=_options(), phase=ReadinessPhase.AFTER_ACTION
        )
        assert report.status == "ready"
        assert tab.url == readiness_site + "/frame"


async def test_visible_busy_content_defers_readiness_and_hidden_busy_content_does_not(
    readiness_site,
):
    async with ChromeBrowser(Launch(url=readiness_site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab, options=_options())
        await tab.evaluate("""
            box.setAttribute('aria-busy','true');
            host.innerHTML='<div hidden><p aria-busy=true>Hidden loader</p></div>';
            setTimeout(()=>box.removeAttribute('aria-busy'),200);
        """)
        report = await wait_for_page(
            tab, options=_options(), phase=ReadinessPhase.OBSERVATION
        )
        assert report.status == "ready"
        assert await tab.evaluate("box.hasAttribute('aria-busy')") == "false"


async def test_timeout_reaches_the_next_model_iteration_with_an_explicit_receipt(
    readiness_site,
):
    model = ScriptedModel(["Done"])
    agent = Agent(
        model=model,
        plugins=browser_plugins(
            Launch(url=readiness_site),
            readiness=_options(timeout=0.5, action_min_ms=0),
            local_files=False,
        ),
    )
    async with agent.session() as session:
        browser, observe = session.ctx[Browser], session.ctx[Observe]
        await observe.capture()

        async def start_ticker(tab):
            await tab.evaluate(
                "window.ticker=setInterval(()=>shadow.firstChild.textContent=Date.now(),10)"
            )
            return Effect("Ticker started.")

        result = await session.ctx[Actions].run(
            kind=ActionKind.CLICK, operation=start_ticker
        )
        assert result.break_chain and "degraded" in result.text
        ends = [
            event
            for event in session.events
            if isinstance(event, ReadinessDegradedEvent)
        ]
        assert len(ends) == 1 and ends[0].timed_out
        async with asyncio.timeout(2):
            await session.run("Inspect the page")
        assert observe.snapshot.readiness == "degraded"
        assert "budget exhausted" in str(model.requests[-1].messages)
        assert not any(
            isinstance(event, ReadinessDegradedEvent) for event in session.events
        )

        async def interact(tab):
            await tab.evaluate("box.dataset.clicked='yes'")
            return Effect("Interacted with the usable page.")

        # Continuous activity must not permanently prevent deliberate input on
        # controls delivered in the degraded observation.
        result = await session.ctx[Actions].run(
            kind=ActionKind.CLICK, operation=interact
        )
        assert result.break_chain
        assert await browser.active_tab.evaluate("box.dataset.clicked") == '"yes"'
        await browser.active_tab.evaluate("clearInterval(ticker)")


def _options(**kwargs):
    return ReadinessOptions(
        **{
            "timeout": 2,
            "quiet_ms": 75,
            "navigation_min_ms": 100,
            "poll_interval": 0.02,
            **kwargs,
        }
    )
