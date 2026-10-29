import errno
from unittest.mock import Mock

import pytest

from browserrig.browser.config import LaunchBrowser
from browserrig.browser.process import ChromeProcess


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
    process.profile = profile
    await process.aclose()
    assert profile.cleanup.call_count == 2
    assert process.profile is None
    await process.aclose()
    assert profile.cleanup.call_count == 2


async def test_profile_cleanup_propagates_unexpected_errors_and_retains_ownership() -> None:
    process = ChromeProcess(LaunchBrowser())
    profile = Mock()
    error = OSError(errno.EIO, "disk failure")
    profile.cleanup.side_effect = [error, None]
    process.profile = profile

    with pytest.raises(OSError) as caught:
        await process.aclose()
    assert caught.value is error
    assert profile.cleanup.call_count == 1
    assert process.profile is profile

    await process.aclose()
    assert profile.cleanup.call_count == 2
    assert process.profile is None
