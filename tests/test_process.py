# Internal state is inspected to verify lifecycle and cleanup.
# pylint: disable=protected-access

from unittest.mock import Mock

from browserrig.browser.config import LaunchBrowser
from browserrig.browser.process import ChromeProcess, _active_endpoint


async def test_profile_cleanup_retries_transient_locks_and_retains_ownership():
    process = ChromeProcess(LaunchBrowser())
    profile = Mock()
    profile.cleanup.side_effect = [PermissionError("temporary handle"), None]
    process._profile = profile
    await process.aclose()
    assert profile.cleanup.call_count == 2
    assert process._profile is None
    await process.aclose()
    assert profile.cleanup.call_count == 2


def test_startup_retries_locked_and_incomplete_port_file():
    path = Mock()
    path.read_text.side_effect = [PermissionError(), "9222\n", "9222\n/devtools/browser/test\n"]
    assert _active_endpoint(path) is None
    assert _active_endpoint(path) is None
    assert _active_endpoint(path) == "ws://127.0.0.1:9222/devtools/browser/test"
