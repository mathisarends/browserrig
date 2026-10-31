"""uv run python -m examples.direct_browser --url https://example.com"""

import argparse
import asyncio

from browserrig import ChromeBrowser, LaunchBrowser, wait_for_page
from browserrig.observation import DomCapture, capture, render


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start Chrome and inspect a page without an LLM"
    )
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    async with ChromeBrowser(
        LaunchBrowser(url=args.url, headless=not args.headed)
    ) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        snapshot = await capture(tab, DomCapture(), report)
        print(render(snapshot))


if __name__ == "__main__":
    asyncio.run(main())
