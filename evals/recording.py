"""Compose benchmark authentication and HAR recording in the same Chrome."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from browserrig.browser import Launch

from .environments import Environments
from .plugins import NetworkRecording
from .plugins.authentication import authenticate
from .task import Task

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext


@asynccontextmanager
async def recording_browser(
    task: Task, environments: Environments, workspace: Path, *, headless: bool
) -> AsyncGenerator[tuple[str, str]]:
    # Playwright is eval-only; Browserrig owns Chrome and all agent actions.
    from playwright.async_api import async_playwright  # pylint: disable=import-outside-toplevel

    async with (
        Launch(headless=headless).process() as process,
        async_playwright() as playwright,
    ):
        browser = await playwright.chromium.connect_over_cdp(process.endpoint)
        try:
            storage = await authenticate(browser, task, environments)
            async with NetworkRecording(workspace / "network.har").context(
                browser, storage
            ) as context:
                target = await _open_task(context, task, environments)
                yield process.endpoint, target
        finally:
            await browser.close()


async def _open_task(
    context: BrowserContext, task: Task, environments: Environments
) -> str:
    pages = []
    for url in task.start_urls:
        page = await context.new_page()
        await page.goto(environments.render(url))
        pages.append(page)
    first = pages[0]
    session = await context.new_cdp_session(first)
    info = await session.send("Target.getTargetInfo")
    await session.detach()
    await first.bring_to_front()
    return info["targetInfo"]["targetId"]
