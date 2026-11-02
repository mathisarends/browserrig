import pytest

from browserrig import ChromeBrowser, Connect

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("isolated", [False, True])
async def test_attached_tabs_and_last_tab_replacement_keep_the_original_context(
    isolated,
):
    async with ChromeBrowser() as owner:
        if isolated:
            first = owner.active_tab.id
            sibling = (await owner.tabs.open()).id
        else:
            first = (
                await owner.client.target.create_target(url="about:blank")
            ).target_id
            sibling = (
                await owner.client.target.create_target(url="about:blank")
            ).target_id
        info = await owner.client.target.get_target_info(target_id=first)
        context_id = info.target_info.browser_context_id
        options = Connect(endpoint=owner.client.transport.url, target_id=first)
        async with ChromeBrowser(options) as connected:
            assert {tab.id for tab in await connected.tabs.list()} == {first}
            opened = await connected.tabs.open()
            info = await owner.client.target.get_target_info(target_id=opened.id)
            assert info.target_info.browser_context_id == context_id
            assert sibling not in {tab.id for tab in await connected.tabs.list()}
            await connected.tabs.close(first)
            replacement = await connected.tabs.close(opened.id)
            info = await owner.client.target.get_target_info(target_id=replacement.id)
            assert info.target_info.browser_context_id == context_id
        # Disconnecting the attached client leaves the externally owned context alive.
        info = await owner.client.target.get_target_info(target_id=replacement.id)
        assert info.target_info.browser_context_id == context_id
