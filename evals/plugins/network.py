"""Playwright HAR recording for offline evaluation, outside the agent workspace."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, StorageState


@dataclass(frozen=True)
class NetworkRecording:
    path: Path

    @asynccontextmanager
    async def context(
        self,
        browser: Browser,
        storage: StorageState,
    ) -> AsyncGenerator[BrowserContext]:
        context = await browser.new_context(
            storage_state=storage,
            locale="en-US",
            timezone_id="UTC",
            viewport={"width": 1280, "height": 720},
            record_har_path=self.path,
            record_har_content="embed",
            record_har_mode="full",
        )
        try:
            yield context
        finally:
            # Closing flushes embedded bodies. Finish even if cancellation arrives
            # during cleanup, before the browser closes or the evaluator starts.
            closing = asyncio.create_task(context.close())
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await closing
                raise
