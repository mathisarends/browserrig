import asyncio
from contextlib import suppress
from dataclasses import dataclass

from harnessed import Plugin, PluginState, hook
from harnessed.kernel import Scope, needs

from browserrig.browser import Browser, Tab, TabChanged
from browserrig.core import BrowserError
from browserrig.events import TAB_STRIP_EVENTS, TabUpdatedEvent

# A slow icon host costs only the strip state, never the session.
_STRIP_SECONDS = 10


class TabStrip(Plugin):
    """Stream what a viewer's tab strip shows: url, title, loading state and favicon.

    Once a page stops loading, its document title and icon are read in the background,
    so a slow icon host never holds up other events. Without this plugin no tab-strip
    events are emitted and no icons are fetched.
    """

    events = TAB_STRIP_EVENTS
    # Each open tab's strip in this session.
    _strips = PluginState[dict[str, "_Strip"]](dict)
    _browser = needs(Browser)

    async def setup(self, ctx: Scope) -> None:
        ctx.effect(self._stop)
        # Tabs opened before this plugin started show up once, with what they show now.
        with suppress(BrowserError):
            tab = self._browser.active_tab
            await self._changed(tab, settled=not tab.loading)

    @hook(TabChanged)
    async def _on_change(self, event: TabChanged) -> None:
        await self._changed(event.tab, settled=event.settled)

    async def _changed(self, tab: Tab, *, settled: bool) -> None:
        if tab.closed:
            if strip := self._strips.pop(tab.id, None):
                strip.cancel()
            return
        strip = self._strips.setdefault(tab.id, _Strip())
        await strip.publish(tab)
        if settled:
            strip.cancel()
            strip.task = asyncio.create_task(
                strip.read(tab), name=f"browserrig:tab-strip:{tab.id}"
            )

    async def _stop(self) -> None:
        tasks = [strip.task for strip in self._strips.values() if strip.task]
        for strip in self._strips.values():
            strip.cancel()
        self._strips.clear()
        await asyncio.gather(*tasks, return_exceptions=True)


@dataclass
class _Strip:
    """What one tab's strip shows, and the read that may still update it."""

    title: str = ""
    # Chrome's title as last seen; a new one replaces whatever the document said.
    chrome_title: str = ""
    icon_url: str = ""
    favicon: str = ""
    shown: tuple[str, str, bool, str] | None = None
    task: asyncio.Task[None] | None = None

    async def publish(self, tab: Tab) -> None:
        """Emit the strip state, once per distinct state."""
        if tab.title != self.chrome_title:
            self.chrome_title = tab.title
            self.title = tab.title
        state = (tab.url, self.title, tab.loading, self.favicon)
        if tab.closed or state == self.shown:
            return
        self.shown = state
        await tab.emit(
            TabUpdatedEvent(
                url=tab.url, title=self.title, loading=tab.loading, favicon=self.favicon
            )
        )

    async def read(self, tab: Tab) -> None:
        try:
            async with asyncio.timeout(_STRIP_SECONDS):
                if tab.dialog is None:
                    strip = await tab.read_strip()
                    # Chrome's target info often keeps the host as title; the document knows.
                    self.title = strip.title or self.title
                    if strip.icon != self.icon_url:
                        # The title should not wait for the icon.
                        await self.publish(tab)
                        self.icon_url = strip.icon
                        self.favicon = (
                            await tab.load_icon(strip.icon) if strip.icon else ""
                        )
                await self.publish(tab)
        except Exception:  # pylint: disable=broad-exception-caught
            # Navigation, dialogs and detached sessions only cost the strip state.
            return

    def cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.task = None
