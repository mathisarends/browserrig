"""A native-input walkthrough; only model-thinking receipts are scripted."""

import asyncio
import base64
import json
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from harnessed.kernel import Scope

from browserrig import Browser, Input, Point, wait_for_page
from browserrig.browser import Tab, screenshot
from browserrig.choreography import BarTypedEvent, HighlightElementEvent, scenes
from browserrig.core import ActivityKind, ActivityOutcome, BrowserBar
from browserrig.events import (
    ActivityFinishedEvent,
    ActivityStartedEvent,
    DownloadCompletedEvent,
    FilesUploadedEvent,
)
from browserrig.observation import extract_document, search_content
from browserrig.tools import NavigateIntent, SearchIntent, UploadIntent


class VisualWalkthrough:
    def __init__(self, browser: Browser, ctx: Scope, directory: Path, url: str):
        self.browser = browser
        self.scope = ctx
        self.input = ctx[Input]
        self.directory = directory
        self.url = url
        self.shots: list[dict[str, str | float]] = []
        self._started = monotonic()

    @property
    def tab(self) -> Tab:
        return self.browser.active_tab

    async def run(self) -> None:
        await wait_for_page(self.tab)
        await self._pointer()
        await self._keyboard()
        await self.capture("observation", "Clean model view", overlays=False)
        await asyncio.sleep(0.8)
        await self._scroll()
        await self._find()
        await self._files()
        await self._navigate()
        await self._tabs()
        await self._thinking()

    async def capture(self, name: str, title: str, *, overlays: bool = True) -> None:
        await self.tab.evaluate(
            "new Promise(resolve => requestAnimationFrame(() => "
            "requestAnimationFrame(() => resolve(true))))"
        )
        encoded = await screenshot(self.tab, overlays=overlays)
        (self.directory / f"{name}.png").write_bytes(base64.b64decode(encoded))
        self.shots.append(
            {
                "file": f"{name}.png",
                "title": title,
                "at": round(monotonic() - self._started, 3),
            }
        )

    async def compact(self) -> None:
        await wait_for_page(self.tab)
        point, _ = await self._target("#query")
        await self.input.mouse.click(point)
        await self.input.keyboard.type_text("Präzision")
        await self.input.keyboard.press_key("a", hold_control=True)
        await self.capture("compact", "Compact · complete German keyboard")

    async def _target(self, selector: str):
        expression = """(() => {
          const rect = document.querySelector(SELECTOR).getBoundingClientRect();
          return {x:rect.x, y:rect.y, width:rect.width, height:rect.height};
        })()""".replace("SELECTOR", json.dumps(selector))
        rect = json.loads(await self.tab.evaluate(expression))
        return Point(
            x=rect["x"] + rect["width"] / 2, y=rect["y"] + rect["height"] / 2
        ), rect

    async def _highlight(self, selector: str) -> Point:
        point, rect = await self._target(selector)
        await self.tab.emit(HighlightElementEvent(ref=selector, **rect))
        return point

    async def _during(self, operation, name: str, title: str, delay: float) -> None:
        task = asyncio.create_task(operation)
        try:
            await asyncio.sleep(delay)
            await self.capture(name, title)
        finally:
            await task

    async def _pointer(self) -> None:
        point = await self._highlight("#open")
        await self.input.mouse.move_to(point)
        await self.capture("pointer", "Pointer · precise target corners")
        await self.input.mouse.click(point)
        assert (
            json.loads(
                await self.tab.evaluate("document.querySelector('#open').textContent")
            )
            == "Notes opened"
        )

    async def _keyboard(self) -> None:
        point = await self._highlight("#query")
        await self.input.mouse.click(point)
        await self.input.keyboard.type_text("Präzise Browser-Eingaben")
        await self.input.keyboard.press_key("a", hold_control=True)
        await self.capture("keyboard", "German keyboard · native Ctrl + A")
        assert (
            json.loads(
                await self.tab.evaluate("document.querySelector('#query').value")
            )
            == "Präzise Browser-Eingaben"
        )

    async def _scroll(self) -> None:
        point = Point(x=950, y=480)
        await self.input.mouse.move_to(point)
        await self._during(
            self.input.mouse.scroll(delta_y=580, point=point),
            "scroll",
            "Scroll · direction and wheel",
            0.08,
        )

    async def _find(self) -> None:
        intent = SearchIntent(queries=("trace",))

        async def step():
            content = await extract_document(self.tab, full_page=False)
            return search_content(content, intent.queries, start=0, count=20)

        await self._during(
            scenes.search(scenes.Scene(self.tab, "proof-find"), intent, step),
            "find",
            "Search · matching page records",
            0.45,
        )

    async def _files(self) -> None:
        await self.input.mouse.scroll(delta_y=-1800, point=Point(x=950, y=480))
        completed = asyncio.get_running_loop().create_future()

        async def received(event: DownloadCompletedEvent):
            if not completed.done():
                completed.set_result(event.filename)

        remove = self.scope.on(DownloadCompletedEvent, received)
        try:
            download, _ = await self._target("#download")
            await self.input.mouse.click(download)
            upload = await self._highlight("#upload")
            await self.input.mouse.click(upload)
            path = self.directory / "session-notes.txt"
            path.write_text("Browserrig native upload proof.\n", encoding="utf-8")
            intent = UploadIntent(paths=(str(path.resolve()),), point=upload)

            async def step():
                tree = await self.tab.cdp.dom.get_document()
                node = await self.tab.cdp.dom.query_selector(
                    node_id=tree.root.node_id, selector="#upload-input"
                )
                described = await self.tab.cdp.dom.describe_node(node_id=node.node_id)
                await (await self.tab.main_frame()).upload_files(
                    described.node.backend_node_id, list(intent.paths)
                )
                await self.tab.emit(
                    FilesUploadedEvent(paths=intent.paths, ref="upload-input")
                )

            await self._during(
                scenes.upload(scenes.Scene(self.tab, "proof-upload"), intent, step),
                "files",
                "Files · real download and native upload",
                0.14,
            )
            assert await asyncio.wait_for(completed, 8) == "browser-notes.txt"
            assert (
                json.loads(
                    await self.tab.evaluate(
                        "document.querySelector('#upload-input').files[0].name"
                    )
                )
                == "session-notes.txt"
            )
            await asyncio.sleep(2.3)
        finally:
            await remove()

    async def _navigate(self) -> None:
        parsed = urlsplit(self.url)
        intent = NavigateIntent(url=self.url + "/notes", typed=parsed.netloc + "/notes")

        async def step():
            await self.tab.navigate(intent.url)

        async def submitted(event: BarTypedEvent):
            if event.browser_bar == BrowserBar.ADDRESS and event.key == "Enter":
                await self.capture("navigation", "Navigation · address entry")

        remove = self.scope.on(BarTypedEvent, submitted, priority=10)
        try:
            await scenes.navigate(
                scenes.Scene(self.tab, "proof-navigation"), intent, step
            )
        finally:
            await remove()
        await wait_for_page(self.tab)

    async def _tabs(self) -> None:
        await self._during(
            self.browser.tabs.open(self.url),
            "tabs",
            "Tabs · staged press and native switch",
            0.18,
        )
        current = self.tab.id
        await wait_for_page(self.tab)
        await self.browser.tabs.close(current)

    async def _thinking(self) -> None:
        await self.input.mouse.move_to(Point(x=840, y=230))
        started = monotonic()
        await self.tab.emit(
            ActivityStartedEvent(
                interval_id="proof-thinking",
                kind=ActivityKind.LLM,
                cause_id="scripted-demo",
            )
        )
        async with asyncio.timeout(3):
            while not json.loads(
                await self.tab.evaluate(
                    "document.querySelector('iframe')?.contentDocument"
                    "?.querySelector('#cursor')?.dataset.thinking === 'true'"
                )
            ):
                await asyncio.sleep(0.01)
        await self.capture("thinking", "Thinking · scripted model-activity receipt")
        await asyncio.sleep(0.6)
        await self.tab.emit(
            ActivityFinishedEvent(
                interval_id="proof-thinking",
                kind=ActivityKind.LLM,
                cause_id="scripted-demo",
                started_at=started,
                outcome=ActivityOutcome.COMPLETED,
            )
        )
