"""Benchmark account setup, outside the agent and its time budget."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from evals.environments import Environments, Site
from evals.task import Task

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, StorageState


async def authenticate(
    browser: Browser, task: Task, environments: Environments
) -> StorageState:
    context = await browser.new_context(locale="en-US", timezone_id="UTC")
    try:
        for name in task.sites:
            await _login(context, name, environments.sites[name])
        return await context.storage_state()
    finally:
        await context.close()


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
        response = None
        for _ in range(10):
            response = await page.goto(site.url.rstrip("/") + paths[name])
            if response is None or response.status not in {502, 503, 504}:
                break
            await asyncio.sleep(2)
        if response is None or response.status >= 400:
            raise RuntimeError(f"Login page unavailable for {name}")
        if name == "reddit":
            await page.get_by_role("link", name="Log in", exact=True).click()
        await page.get_by_label(username, exact=True).fill(site.username)
        await page.get_by_label(password, exact=True).fill(
            site.password.get_secret_value()
        )
        # Cold GitLab redirects can outlive the click's implicit navigation wait.
        # Submit once, then give the authenticated page its own bounded wait.
        await page.get_by_role("button", name=submit, exact=True).click(
            no_wait_after=True
        )
        await page.wait_for_function(
            "!document.querySelector('input[type=password]')", timeout=60_000
        )
    finally:
        await page.close()
