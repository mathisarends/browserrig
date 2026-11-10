"""Free local integration check: Browserrig actions must reach the official HAR."""

import json

import pytest

from browserrig.browser import ChromeBrowser, Connect
from evals.environments import Environments
from evals.recording import recording_browser
from evals.task import load_tasks


@pytest.mark.integration
async def test_browserrig_records_navigation_in_the_playwright_context(site, tmp_path):
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
