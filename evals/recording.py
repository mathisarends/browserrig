"""Authenticate and record standard HAR while Browserrig drives the same Chrome."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from browserrig.browser import Launch

from .environments import Environments, Site
from .task import Task

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext


@asynccontextmanager
async def recording_browser(
    task: Task, environments: Environments, workspace: Path, *, headless: bool
) -> AsyncGenerator[tuple[str, str]]:
    # Playwright is an eval-only dependency; browserrig still owns Chrome and all agent actions.
    # pylint: disable=import-outside-toplevel
    from playwright.async_api import async_playwright

    async with (
        Launch(headless=headless).process() as process,
        async_playwright() as playwright,
    ):
        browser = await playwright.chromium.connect_over_cdp(process.endpoint)
        try:
            storage = await _authenticate(browser, task, environments)

            context = await browser.new_context(
                storage_state=storage,
                locale="en-US",
                timezone_id="UTC",
                viewport={"width": 1280, "height": 720},
                record_har_path=workspace / "network.har",
                record_har_content="embed",
                record_har_mode="full",
            )
            try:
                target = await _open_task(context, task, environments)
                yield process.endpoint, target
            finally:
                # HAR must be flushed before the official offline evaluator reads it.
                await context.close()
        finally:
            await browser.close()


async def _authenticate(browser, task: Task, environments: Environments):
    context = await browser.new_context(locale="en-US", timezone_id="UTC")
    try:
        for name in task.sites:
            await _login(context, name, environments.sites[name])
        return await context.storage_state()
    finally:
        await context.close()


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


async def _login(context: BrowserContext, name: str, site: Site) -> None:
    if not site.username:
        return
    paths = {
        "shopping": "/customer/account/login/",
        "shopping_admin": "/",
        "gitlab": "/users/sign_in",
        "reddit": "/",
    }
    labels = {
        "shopping": ("Email", "Password", "Sign In"),
        "shopping_admin": ("Username", "Password", "Sign in"),
        "gitlab": ("Username or email", "Password", "Sign in"),
        "reddit": ("Username", "Password", "Log in"),
    }
    username, password, submit = labels[name]
    page = await context.new_page()
    try:
        response = await page.goto(site.url.rstrip("/") + paths[name])
        if response is None or response.status >= 400:
            raise RuntimeError(f"Login page unavailable for {name}")
        if name == "reddit":
            await page.get_by_role("link", name="Log in", exact=True).click()
        await page.get_by_label(username, exact=True).fill(site.username)
        await page.get_by_label(password, exact=True).fill(
            site.password.get_secret_value()
        )
        await page.get_by_role("button", name=submit, exact=True).click()
        await page.wait_for_function(
            "!document.querySelector('input[type=password]')", timeout=20_000
        )
    finally:
        await page.close()
