import json
import re

import pytest
from harnessed import ToolCall
from harnessed.models import ModelChunk
from harnessed.testing import CallbackModel

from browserrig import (
    Agent,
    Browser,
    BrowserPerception,
    Chrome,
    DomCapture,
    Files,
    LocalWorkspace,
    wait_for_page,
)
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_agent_extracts_searches_and_reads_only_the_requested_excerpt(
    site, tmp_path
):
    step = 0
    saved_path = ""

    async def respond(request):
        nonlocal step, saved_path
        if step == 0:
            yield ModelChunk(tool_call=ToolCall("extract_content", {}))
        elif step == 1:
            receipt = next(
                (
                    message.text
                    for message in reversed(request.messages)
                    if message.text.startswith("Saved: ")
                ),
                None,
            )
            assert receipt is not None
            saved_path = receipt.splitlines()[0].removeprefix("Saved: ")
            assert receipt.splitlines()[:3] == [
                f"Saved: {saved_path}",
                f"Source: {site}/",
                "Title: Saved report",
            ]
            assert "LARGE_BODY_LINE" not in "\n".join(
                message.text for message in request.messages
            )
            yield ModelChunk(
                tool_call=ToolCall(
                    "grep", {"query": "RELEVANT_MARKER", "pattern": saved_path}
                )
            )
        elif step == 2:
            match = next(
                (
                    re.search(r"offset=(\d+)", message.text)
                    for message in reversed(request.messages)
                    if re.search(r"offset=(\d+)", message.text)
                ),
                None,
            )
            assert match is not None
            yield ModelChunk(
                tool_call=ToolCall(
                    "read_file",
                    {"path": saved_path, "offset": int(match[1]), "max_chars": 500},
                )
            )
        else:
            reply = next(
                (
                    message.text
                    for message in reversed(request.messages)
                    if '"text":' in message.text
                ),
                None,
            )
            assert reply is not None
            assert "RELEVANT_MARKER" in json.loads(reply)["text"]
            yield ModelChunk(text="Found the relevant passage")
        step += 1

    agent = Agent(
        model=CallbackModel(respond),
        browser=Chrome.launch(url=site),
        plugins=[
            Files(LocalWorkspace(tmp_path)),
            BrowserPerception(
                capture=DomCapture(max_text_chars=0, sparse_text_chars=0)
            ),
        ],
    )
    async with agent.session() as session:
        tab = session.scope[Browser].active_tab
        await wait_for_page(tab)
        text = "LARGE_BODY_LINE\n" * 6000 + "RELEVANT_MARKER"
        await evaluate(
            tab,
            "document.title='Saved report';"
            "document.body.innerHTML='<main><h1>Report</h1><pre></pre></main>';"
            f"document.querySelector('pre').textContent={json.dumps(text)}",
        )
        result = await session.run(
            "Save the page and read the passage around RELEVANT_MARKER"
        )
        assert result.completed
        extraction = session.scope[BrowserPerception].extracted_content
        assert extraction is not None and extraction.extracted_path == saved_path
        assert "RELEVANT_MARKER" in extraction.markdown
    assert step == 4
    assert (tmp_path / saved_path).read_text(encoding="utf-8").count(
        "LARGE_BODY_LINE"
    ) == 6000
