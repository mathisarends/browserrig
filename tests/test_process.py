# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

import asyncio
import errno
from unittest.mock import Mock

import pytest

from browserrig.browser.config import LaunchBrowser
from browserrig.browser.process import ChromeProcess, _active_endpoint


@pytest.mark.parametrize(
    "error",
    [PermissionError("temporary handle"), OSError(errno.ENOTEMPTY, "late cache write")],
    ids=["locked-file", "directory-repopulated"],
)
async def test_profile_cleanup_retries_transient_errors_and_retains_ownership(
    error: OSError,
) -> None:
    process = ChromeProcess(LaunchBrowser())
    profile = Mock()
    profile.cleanup.side_effect = [error, None]
    process._profile = profile
    await process.aclose()
    assert profile.cleanup.call_count == 2
    assert process._profile is None
    await process.aclose()
    assert profile.cleanup.call_count == 2


async def test_profile_cleanup_propagates_unexpected_errors_and_retains_ownership() -> (
    None
):
    process = ChromeProcess(LaunchBrowser())
    profile = Mock()
    error = OSError(errno.EIO, "disk failure")
    profile.cleanup.side_effect = [error, None]
    process._profile = profile
    with pytest.raises(OSError) as caught:
        await process.aclose()
    assert caught.value is error
    assert profile.cleanup.call_count == 1
    assert process._profile is profile
    await process.aclose()
    assert profile.cleanup.call_count == 2
    assert process._profile is None


def test_startup_retries_locked_and_incomplete_port_file():
    path = Mock()
    path.read_text.side_effect = [
        PermissionError(),
        "9222\n",
        "9222\n/devtools/browser/test\n",
    ]
    assert _active_endpoint(path) is None
    assert _active_endpoint(path) is None
    assert _active_endpoint(path) == "ws://127.0.0.1:9222/devtools/browser/test"


async def test_profile_cleanup_gives_up_on_persistent_lock_without_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = ChromeProcess(LaunchBrowser())
    profile = Mock()
    profile.name = "missing-profile-dir"
    profile.cleanup.side_effect = PermissionError("held by a Chrome helper")
    process._profile = profile
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    monkeypatch.setattr(asyncio.get_running_loop(), "time", lambda: next(clock))
    await process.aclose()
    assert process._profile is None


async def _no_sleep(_: float) -> None:
    return None
