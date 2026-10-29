from unittest.mock import Mock

from browserrig.browser.config import LaunchBrowser
from browserrig.browser.process import ChromeProcess


async def test_profile_cleanup_retries_transient_locks_and_retains_ownership():
    process = ChromeProcess(LaunchBrowser())
    profile = Mock()
    profile.cleanup.side_effect = [PermissionError("temporary handle"), None]
    process.profile = profile
    await process.aclose()
    assert profile.cleanup.call_count == 2
    assert process.profile is None
    await process.aclose()
    assert profile.cleanup.call_count == 2
