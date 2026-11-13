from unittest.mock import AsyncMock

from harnessed import Agent, ToolCall
from harnessed.events import ToolCallFinishedEvent
from harnessed.models import ModelChunk
from harnessed.testing import ScriptedModel

from browserrig import Browser, PageSearchTools, Readiness, Secret, Secrets
from browserrig.observation.content import PageContent
from browserrig.tools import search as search_module
from tests.fakes import FakeChrome

_ROWS = """| Name | Email |
| --- | --- |
| Adam Garcia | adam.garcia@example.org |
| Bob Jones | bbjones@example.org |
"""


async def test_searches_in_one_batch_return_records_without_another_observation(
    monkeypatch,
):
    capture = AsyncMock(
        return_value=PageContent(
            url="https://shop.test/customers", title="Customers", markdown=_ROWS
        )
    )
    monkeypatch.setattr(search_module, "extract_document", capture)
    agent = Agent(
        model=ScriptedModel(
            [
                [
                    ModelChunk(tool_call=ToolCall("search_page", {"query": "garcia"})),
                    ModelChunk(
                        tool_call=ToolCall(
                            "search_page",
                            {"query": "missing", "alternatives": ["BBJONES"]},
                        )
                    ),
                ],
                "Done",
            ]
        ),
        plugins=[FakeChrome({}), Readiness(), PageSearchTools()],
    )
    async with agent.session() as session:
        result = await session.run("Find customers")
        tab = session.scope[Browser].active_tab
    first, second = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert not first.is_error and not second.is_error
    assert first.text.splitlines()[2:] == [
        "| Name | Email |",
        "| Adam Garcia | adam.garcia@example.org |",
    ]
    assert second.text.splitlines()[0].startswith(
        '1 record matches "missing" | "BBJONES"'
    )
    assert second.text.splitlines()[-1] == "| Bob Jones | bbjones@example.org |"
    capture.assert_awaited_with(tab, full_page=False)
    assert capture.await_count == 2


async def test_secrets_are_redacted_before_they_can_be_matched(monkeypatch):
    secret = "hunter2-credential"
    capture = AsyncMock(
        return_value=PageContent(
            url="https://example.org/",
            title="Account",
            markdown=f"Password hint: {secret}",
        )
    )
    monkeypatch.setattr(search_module, "extract_document", capture)
    agent = Agent(
        model=ScriptedModel(
            [
                [ModelChunk(tool_call=ToolCall("search_page", {"query": "hunter2"}))],
                [ModelChunk(tool_call=ToolCall("search_page", {"query": "hint"}))],
                "Done",
            ]
        ),
        plugins=[
            FakeChrome({}),
            Readiness(),
            Secrets({"KEY": Secret(secret, domains=("example.org",))}),
            PageSearchTools(),
        ],
    )
    async with agent.session() as session:
        result = await session.run("Search")
    missing, hint = [
        event.result
        for event in result.events
        if isinstance(event, ToolCallFinishedEvent)
    ]
    assert missing.text.startswith("0 records match")
    assert secret not in hint.text and "{{secret:" in hint.text
