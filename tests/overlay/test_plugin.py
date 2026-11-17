import pytest

from browserrig import ChoreographyOverlay
from browserrig.browser import TabChanged
from browserrig.choreography import (
    Choreography,
    DownloadPresentedEvent,
    WorkPhase,
)
from browserrig.events import CursorStateEvent, DownloadStartedEvent, EventKind
from tests.fakes import mounted


class _Surface:
    """A tab's overlay surface that keeps every message the overlay sends."""

    def __init__(self):
        self.mounts = 0
        self.sent = []

    async def mount(self, *, html, script):
        assert html and script
        self.mounts += 1
        return self

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        pass


def _download(phase=WorkPhase.RUNNING):
    return DownloadPresentedEvent(
        download_id="d", filename="a.pdf", phase=phase, target_id="tab-1"
    )


async def test_overlay_cannot_mount_without_choreography():
    with pytest.raises(Exception, match="Choreography"):
        async with mounted(ChoreographyOverlay()):
            pass


async def test_overlay_draws_presented_events_but_never_browser_facts():
    async with mounted(Choreography(), ChoreographyOverlay(theme="light")) as (
        services,
        ctx,
    ):
        surface = services.browser.active_tab.overlays = _Surface()
        await ctx.dispatch(
            DownloadStartedEvent(download_id="d", filename="a.pdf", url="https://x/")
        )
        await ctx.dispatch(_download())
        await ctx.dispatch(CursorStateEvent(x=1, y=2, target_id="another-tab"))
        await ctx.dispatch(CursorStateEvent(x=10, y=20, target_id="tab-1"))
    assert surface.mounts == 1
    assert [message["type"] for message in surface.sent] == [
        EventKind.DOWNLOAD_PRESENTED,
        EventKind.CURSOR_STATE,
    ]
    assert surface.sent[0]["presentation"]["theme"] == "light"
    # Only the first message in a document carries the retained receipts.
    assert "restore" in surface.sent[0] and "restore" not in surface.sent[1]


async def test_settled_tab_change_restores_receipts_once_per_document():
    async with mounted(Choreography(), ChoreographyOverlay()) as (services, ctx):
        tab = services.browser.active_tab
        surface = tab.overlays = _Surface()
        await ctx.dispatch(_download())
        tab.document_id = "doc-2"
        await ctx.dispatch(TabChanged(tab, settled=False))
        await ctx.dispatch(TabChanged(tab, settled=True))
        await ctx.dispatch(TabChanged(tab, settled=True))
    restored = surface.sent[-1]
    assert len(surface.sent) == 2 and "type" not in restored
    assert [receipt["download_id"] for receipt in restored["restore"]] == ["d"]
    assert restored["presentation"]["document_id"] == "doc-2"
