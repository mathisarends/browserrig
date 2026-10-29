"""uv run python -m examples.connect_browser --endpoint http://127.0.0.1:9222"""

import argparse
import asyncio

from browserrig import ChromeBrowser, ConnectBrowser, wait_for_page


async def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to an already running CDP browser")
    parser.add_argument("--endpoint", required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--target-id", help="Attach to an existing tab instead of an isolated context"
    )
    selection.add_argument("--url", default="about:blank", help="URL in the new isolated context")
    args = parser.parse_args()
    options = ConnectBrowser(endpoint=args.endpoint, target_id=args.target_id, url=args.url)
    async with ChromeBrowser(options) as browser:
        tab = browser.active_tab
        await wait_for_page(browser, tab)
        print(await tab.evaluate("document.title"))
        print(await browser.tabs())
    # This disconnects our client. The external Chrome process remains alive.


if __name__ == "__main__":
    asyncio.run(main())
