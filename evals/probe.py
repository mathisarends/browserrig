"""Show what the agent would see on a live page, without a model.

uv run python -m evals.probe https://stripe.com/pricing --extract
uv run python -m evals.probe https://example.com --js "document.title"
"""

import argparse
import asyncio

from browserrig import ChromeBrowser, LaunchBrowser, wait_for_page
from browserrig.observation import DomCapture, capture, render
from browserrig.observation.content import extract_content


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--extract", action="store_true", help="Print extract_content")
    parser.add_argument("--full-page", action="store_true")
    parser.add_argument("--max-chars", type=int, default=50000)
    parser.add_argument("--no-observe", action="store_true")
    parser.add_argument("--js", action="append", default=[], help="Evaluate after load")
    parser.add_argument("--wait", type=float, default=0, help="Extra seconds after load")
    args = parser.parse_args()
    async with ChromeBrowser(LaunchBrowser(url=args.url)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        if args.wait:
            await asyncio.sleep(args.wait)
        for expression in args.js:
            print(f"--- js: {expression[:80]}\n{await tab.evaluate(expression)}")
        if not args.no_observe:
            snapshot = await capture(tab, DomCapture(), report)
            text = render(snapshot)
            print(f"--- observation ({len(text)} chars)\n{text}")
        if args.extract:
            content = (
                await extract_content(tab, max_chars=args.max_chars, full_page=args.full_page)
            ).render()
            print(f"--- extract_content ({len(content)} chars)\n{content}")


if __name__ == "__main__":
    asyncio.run(main())
