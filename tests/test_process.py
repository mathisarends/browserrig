import asyncio
import errno
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from browserrig.browser import LaunchBrowser
from browserrig.browser import process as process_module
from browserrig.browser.process import ChromeProcess, _active_endpoint
from browserrig.core import BrowserError


@pytest.mark.parametrize(
    "error",
    [PermissionError("temporary handle"), OSError(errno.ENOTEMPTY, "late cache write")],
    ids=["locked-file", "directory-repopulated"],
)
async def test_profile_cleanup_retries_transient_errors_and_retains_ownership(
    error: OSError, profile: Mock
) -> None:
    profile.cleanup.side_effect = [error, None]
    process = _process()
    with pytest.raises(BrowserError, match="exited during startup"):
        async with process:
            pass
    assert profile.cleanup.call_count == 2
    await process.aclose()
    assert profile.cleanup.call_count == 2


async def test_profile_cleanup_propagates_unexpected_errors_and_retains_ownership(
    profile: Mock,
) -> None:
    error = OSError(errno.EIO, "disk failure")
    profile.cleanup.side_effect = [error, None]
    process = _process()
    with pytest.raises(OSError) as caught:
        async with process:
            pass
    assert caught.value is error
    assert profile.cleanup.call_count == 1
    # The profile is still owned, so the next close retries it once.
    await process.aclose()
    assert profile.cleanup.call_count == 2
    await process.aclose()
    assert profile.cleanup.call_count == 2


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
    monkeypatch: pytest.MonkeyPatch, profile: Mock
) -> None:
    profile.cleanup.side_effect = PermissionError("held by a Chrome helper")
    process = _process()
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(  # smelt: ignore[SMT426] -- sleep is patched; no wait uses this clock
        asyncio.get_running_loop(), "time", lambda: next(clock)
    )
    # The startup error is reported, not the leftover profile.
    with pytest.raises(BrowserError, match="exited during startup"):
        async with process:
            pass
    attempts = profile.cleanup.call_count
    await process.aclose()
    assert profile.cleanup.call_count == attempts


@pytest.fixture(name="profile")
def _profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    """A temporary profile for a Chrome that exits during startup."""
    profile = Mock()
    profile.name = str(tmp_path / "profile")
    monkeypatch.setattr(process_module, "TemporaryDirectory", lambda **_: profile)
    exited = Mock(returncode=1)
    monkeypatch.setattr(
        process_module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=exited),
    )
    return profile


def _process() -> ChromeProcess:
    return ChromeProcess(LaunchBrowser(executable=Path(sys.executable)))


async def _no_sleep(_: float) -> None:
    return None
