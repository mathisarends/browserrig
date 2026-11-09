from types import SimpleNamespace

import pytest
from harnessed import Agent
from harnessed.plugins import Service
from harnessed.testing import ScriptedModel

from browserrig import DownloadReceiving
from browserrig.browser import Browser
from browserrig.files import FileSystem, FileTransfer, LocalWorkspace, MountedWorkspace


@pytest.mark.parametrize("supported", [False, True])
async def test_download_receiving_owns_binding_and_cleanup_without_tools(
    tmp_path, supported
):
    calls = []

    async def receive(transfer):
        calls.append(transfer)
        return supported and transfer is not None

    browser = SimpleNamespace(receive_downloads=receive)
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        transfer = FileTransfer(files, MountedWorkspace())
        agent = Agent(
            model=ScriptedModel([]),
            plugins=[
                Service(Browser, browser),
                Service(FileTransfer, transfer),
                DownloadReceiving(),
            ],
        )
        async with agent.session() as session:
            assert session.scope[DownloadReceiving].receiving is supported
            assert calls == [transfer]
        assert calls == [transfer, None]


async def test_download_receiving_follows_transfer_replacement_and_removal(tmp_path):
    calls = []

    async def receive(transfer):
        calls.append(transfer)
        return transfer is not None

    browser = SimpleNamespace(receive_downloads=receive)
    agent = Agent(
        model=ScriptedModel([]),
        plugins=[Service(Browser, browser), DownloadReceiving()],
    )
    async with (
        FileSystem(LocalWorkspace(tmp_path / "first")) as first,
        FileSystem(LocalWorkspace(tmp_path / "second")) as second,
        agent.session() as session,
    ):
        assert not session.scope[DownloadReceiving].receiving and not calls
        first_transfer = FileTransfer(first, MountedWorkspace())
        second_transfer = FileTransfer(second, MountedWorkspace())
        first_handle = await session.mount(Service(FileTransfer, first_transfer))
        assert session.scope[DownloadReceiving].receiving
        second_handle = await session.mount(Service(FileTransfer, second_transfer))
        assert calls[-2:] == [None, second_transfer]
        await first_handle.aclose()
        await session.scope.settle()
        assert calls[-1] is second_transfer
        await second_handle.aclose()
        await session.scope.settle()
        assert calls[-1] is None
        assert not session.scope[DownloadReceiving].receiving
