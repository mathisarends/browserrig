import asyncio

import pytest

from browserrig.core import ActionContext


def test_nested_actions_restore_correlation_after_failure():
    actions = ActionContext()
    with actions.activate("outer"):
        with pytest.raises(ValueError), actions.activate("inner"):
            assert actions.action_id == "inner"
            raise ValueError("failed")
        assert actions.action_id == "outer"
    assert actions.action_id == ""


async def test_concurrent_actions_do_not_overwrite_each_others_correlation():
    actions = ActionContext()

    async def run(action_id):
        with actions.activate(action_id):
            await asyncio.sleep(0)
            return actions.action_id

    async with asyncio.timeout(5):
        first, second = await asyncio.gather(run("first"), run("second"))
    assert (first, second, actions.action_id) == ("first", "second", "")


async def test_inherited_action_expires_when_its_parent_operation_finishes():
    actions = ActionContext()
    release = asyncio.Event()

    async def inherited():
        await release.wait()
        return actions.action_id

    async with asyncio.timeout(5), asyncio.TaskGroup() as group:
        with actions.activate("finished"):
            child = group.create_task(inherited())
        release.set()
    assert child.result() == ""
